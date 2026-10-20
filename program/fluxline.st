(* ==================================================================== *)
(*  FLUXLINE - Line 01 . 3-way sorting                                    *)
(*  OpenPLC runtime . IEC 61131-3 Structured Text                          *)
(*                                                                        *)
(*  One belt, four sensors, three lanes and a reject chute.                *)
(*                                                                        *)
(*  Verdict law (fixed, decided at the load cell):                         *)
(*    height >= 165 mm               -> L03 OVERSIZE                       *)
(*    else metal detected            -> L02 STEEL LOOP                     *)
(*    else weight out of 2..12 kg    -> REJECT                             *)
(*    else                           -> L01 APPROVED                       *)
(*                                                                        *)
(*  Geometry, mm from the photo-eye:                                       *)
(*    PE 0    HS 1200    ID 1900    LC 2600                                *)
(*    gates: RJ 2900   L01 3100   L02 3300   L03 3500    belt end 3600     *)
(*                                                                        *)
(*  I/O and register maps: docs/01-io-map.md, docs/02-register-map.md      *)
(*  License: MIT (see LICENSE)                                             *)
(* ==================================================================== *)


(* -------------------------------------------------------------------- *)
(*  Types                                                                *)
(* -------------------------------------------------------------------- *)

TYPE PIECE_T :
STRUCT
  active  : BOOL;      (* slot in use *)
  pos     : REAL;      (* mm from the photo-eye *)
  height  : REAL;      (* mm, latched at HS *)
  metal   : BOOL;      (* latched at ID *)
  weight  : REAL;      (* grams, latched at LC *)
  verdict : INT;       (* 0 none, 1 L01, 2 L02, 3 L03, 4 reject *)
  routed  : BOOL;      (* divert issued and completed *)
  id_done : BOOL;      (* ID window consumed *)
  lc_done : BOOL;      (* LC window consumed, verdict final *)
END_STRUCT;
END_TYPE;


(* -------------------------------------------------------------------- *)
(*  Function blocks                                                      *)
(* -------------------------------------------------------------------- *)

(* Time-based glitch filter. Output follows input only after the signal  *)
(* has been stable for PT. Keeps contact bounce and sensor chatter from  *)
(* reaching the logic.                                                   *)
FUNCTION_BLOCK FB_Debounce
VAR_INPUT
  sig : BOOL;          (* raw signal *)
  pt  : TIME;          (* stability time, both edges *)
END_VAR
VAR_OUTPUT
  q   : BOOL;
END_VAR
VAR
  tOn  : TON;
  tOff : TON;
END_VAR
  tOn(IN := sig, PT := pt);
  tOff(IN := NOT sig, PT := pt);
  q := tOn.Q AND NOT tOff.Q;
END_FUNCTION_BLOCK


(* Rising-edge detector.                                                 *)
FUNCTION_BLOCK FB_RTrig
VAR_INPUT
  sig : BOOL;
END_VAR
VAR_OUTPUT
  q   : BOOL;
END_VAR
VAR
  last : BOOL := FALSE;
END_VAR
  q := sig AND NOT last;
  last := sig;
END_FUNCTION_BLOCK


(* -------------------------------------------------------------------- *)
(*  Main program                                                         *)
(* -------------------------------------------------------------------- *)

PROGRAM FLUXLINE
VAR
  (* ---- digital inputs - see docs/01-io-map.md ---- *)
  pe_raw        AT %IX0.0 : BOOL;  (* photo-eye: piece present *)
  id_raw        AT %IX0.2 : BOOL;  (* inductive probe: metal *)
  estop_chain   AT %IX0.4 : BOOL;  (* E-stop chain: TRUE = healthy, FALSE = tripped *)
  pb_start_raw  AT %IX0.5 : BOOL;  (* start pushbutton *)
  pb_stop_raw   AT %IX0.6 : BOOL;  (* stop pushbutton *)
  gate_confirm  AT %IX0.7 : BOOL;  (* piece has left the belt at a lane gate *)
  chute_pe      AT %IX1.0 : BOOL;  (* reject chute photo-eye *)

  (* ---- analog inputs ---- *)
  height_raw    AT %IW0 : INT;     (* 0..27648 -> 0..400 mm *)
  weight_raw    AT %IW2 : INT;     (* 0..27648 -> 0..30000 g *)
  speed_fb_raw  AT %IW4 : INT;     (* 0..27648 -> 0..600 mm/s *)

  (* ---- digital outputs ---- *)
  belt_run      AT %QX0.0 : BOOL;  (* belt VFD enable *)
  div_l1        AT %QX0.1 : BOOL;  (* diverter L01 solenoid *)
  div_l2        AT %QX0.2 : BOOL;  (* diverter L02 solenoid *)
  div_l3        AT %QX0.3 : BOOL;  (* diverter L03 solenoid *)
  div_rj        AT %QX0.4 : BOOL;  (* reject pusher *)
  lamp_g        AT %QX0.5 : BOOL;  (* stack light green *)
  lamp_a        AT %QX0.6 : BOOL;  (* stack light amber *)
  lamp_r        AT %QX0.7 : BOOL;  (* stack light red *)
  horn          AT %QX1.0 : BOOL;  (* alarm horn *)

  (* ---- word outputs: telemetry over Modbus ---- *)
  sp_raw        AT %QW0 : INT;     (* belt speed setpoint raw *)
  heartbeat     AT %QW1 : INT;     (* increments 1x per second - supervision *)
  state_w       AT %QW2 : INT;     (* 0 INIT 1 IDLE 2 RUN 3 JAM 4 ESTOP *)
  alarm_w       AT %QW3 : INT;     (* bit0 JAM bit1 ESTOP bit2 CHAIN bit3 STALL bit4 FULL *)
  a10           AT %QW4 : INT;     (* availability x10 *)
  p10           AT %QW5 : INT;     (* performance x10 *)
  q10           AT %QW6 : INT;     (* quality x10 *)
  c_l1          AT %QW7 : INT;     (* L01 pieces *)
  c_l2          AT %QW8 : INT;     (* L02 pieces *)
  c_l3          AT %QW9 : INT;     (* L03 pieces *)
  c_rj          AT %QW10 : INT;    (* reject pieces *)
  c_detect      AT %QW11 : INT;    (* detected pieces *)
  c_routed      AT %QW12 : INT;    (* routed pieces, all lanes *)
  ppm           AT %QW13 : INT;    (* rolling pieces per minute *)
  speed_echo    AT %QW14 : INT;    (* belt speed mm/s, derived *)
  version_w     AT %QW19 : INT;    (* program version, 101 = 1.0.1 *)

  (* ---- config: written over Modbus holding registers, clamped below ---- *)
  cfg_tall_mm   AT %QW20 : INT;    (* tall threshold mm.    default 165   *)
  cfg_min_g     AT %QW21 : INT;    (* weight band min g.    default 2000  *)
  cfg_max_g     AT %QW22 : INT;    (* weight band max g.    default 12000 *)
  cfg_jam_s     AT %QW23 : INT;    (* jam watchdog s.       default 8     *)
  cfg_ideal     AT %QW24 : INT;    (* ideal pieces/min.     default 34    *)
  cfg_prearm    AT %QW25 : INT;    (* diverter pre-arm mm.  default 120   *)
  cfg_scan_ms   AT %QW26 : INT;    (* scan period ms.       default 10    *)
  cfg_belt_mms  AT %QW27 : INT;    (* belt speed mm/s.      default 120   *)

  (* ---- debounced inputs ---- *)
  pe        : BOOL;
  id_met    : BOOL;
  pb_start  : BOOL;
  pb_stop   : BOOL;
  deb_pe    : FB_Debounce;
  deb_id    : FB_Debounce;
  deb_start : FB_Debounce;
  deb_stop  : FB_Debounce;
  trig_start : FB_RTrig;
  trig_stop  : FB_RTrig;
  trig_pe    : FB_RTrig;

  (* ---- state machine ---- *)
  state : INT := 0;                (* 0 INIT 1 IDLE 2 RUN 3 JAM 4 ESTOP *)
  estop_latched : BOOL := FALSE;   (* latched fault, needs manual reset *)
  jam_latched   : BOOL := FALSE;
  tracker_full  : BOOL := FALSE;

  (* ---- piece tracking ---- *)
  pieces    : ARRAY[0..15] OF PIECE_T;
  speed_mms : REAL;
  sp_mms    : REAL;
  scan_s    : REAL;
  height_mm : REAL;
  weight_g  : REAL;

  (* ---- geometry, mm from PE ---- *)
  hs_pos   : REAL := 1200.0;
  id_pos   : REAL := 1900.0;
  lc_pos   : REAL := 2600.0;
  hs_win   : REAL := 80.0;
  lc_win   : REAL := 120.0;
  g_rj     : REAL := 2900.0;
  g_l1     : REAL := 3100.0;
  g_l2     : REAL := 3300.0;
  g_l3     : REAL := 3500.0;
  belt_len : REAL := 3600.0;

  (* ---- scaling ---- *)
  raw_max    : REAL := 27648.0;
  height_max : REAL := 400.0;      (* raw full scale -> mm *)
  weight_max : REAL := 30000.0;    (* raw full scale -> g *)
  speed_max  : REAL := 600.0;      (* raw full scale -> mm/s *)

  (* ---- working config, clamped ---- *)
  cfg_tall   : REAL;
  cfg_min    : REAL;
  cfg_max    : REAL;
  jam_lim    : REAL;
  ideal_rate : REAL;
  prearm     : REAL;

  (* ---- watchdogs ---- *)
  jam_s    : REAL := 0.0;          (* seconds the photo-eye has been blocked *)
  quiet_s  : REAL := 0.0;          (* seconds without a new piece while running *)
  stall_on : BOOL := FALSE;

  (* ---- diverter temps ---- *)
  fired    : BOOL;
  cfm      : BOOL;
  gate_end : REAL;

  (* ---- OEE accounting ---- *)
  run_s  : REAL := 0.0;            (* seconds in RUN *)
  down_s : REAL := 0.0;            (* seconds in JAM/ESTOP *)
  missed : INT := 0;               (* pieces that reached the end unrouted *)
  detect_tot : REAL := 0.0;
  route_tot  : REAL := 0.0;
  buckets  : ARRAY[0..59] OF INT;  (* routed pieces, one bucket per second *)
  bucket_i : INT := 0;
  sec_acc  : REAL := 0.0;
  ppm_acc  : INT := 0;
  avail    : REAL;
  perf     : REAL;
  qual     : REAL;

  (* ---- heartbeat / horn ---- *)
  hb_acc  : REAL := 0.0;
  horn_s  : REAL := 0.0;
  horn_on : BOOL := FALSE;

  (* ---- loop temps ---- *)
  i : INT;
  d : INT;
END_VAR


(* ==================================================================== *)
(*  0 . inputs                                                           *)
(* ==================================================================== *)

deb_pe(sig := pe_raw, pt := T#20ms);            pe       := deb_pe.q;
deb_id(sig := id_raw, pt := T#20ms);            id_met   := deb_id.q;
deb_start(sig := pb_start_raw, pt := T#50ms);   pb_start := deb_start.q;
deb_stop(sig := pb_stop_raw, pt := T#50ms);     pb_stop  := deb_stop.q;

trig_start(sig := pb_start);
trig_stop(sig := pb_stop);
trig_pe(sig := pe);

(* The E-stop chain is never debounced - fail-safe means immediate. *)
IF NOT estop_chain THEN
  estop_latched := TRUE;
END_IF;


(* ==================================================================== *)
(*  1 . config                                                           *)
(* ==================================================================== *)

(* Config registers arrive from the HMI or the harness. Zero or nonsense *)
(* values fall back to compiled defaults so the line always has a law.   *)

cfg_tall := INT_TO_REAL(cfg_tall_mm);
IF cfg_tall < 50.0 OR cfg_tall > 380.0 THEN cfg_tall := 165.0; END_IF;

cfg_min := INT_TO_REAL(cfg_min_g);
IF cfg_min < 100.0 OR cfg_min > 8000.0 THEN cfg_min := 2000.0; END_IF;

cfg_max := INT_TO_REAL(cfg_max_g);
IF cfg_max < 4000.0 OR cfg_max > 29000.0 THEN cfg_max := 12000.0; END_IF;
IF cfg_max <= cfg_min THEN cfg_max := cfg_min + 1000.0; END_IF;

jam_lim := INT_TO_REAL(cfg_jam_s);
IF jam_lim < 1.0 OR jam_lim > 60.0 THEN jam_lim := 8.0; END_IF;

ideal_rate := INT_TO_REAL(cfg_ideal);
IF ideal_rate < 1.0 OR ideal_rate > 200.0 THEN ideal_rate := 34.0; END_IF;

prearm := INT_TO_REAL(cfg_prearm);
IF prearm < 20.0 OR prearm > 500.0 THEN prearm := 120.0; END_IF;

scan_s := INT_TO_REAL(cfg_scan_ms) * 0.001;
IF scan_s < 0.001 OR scan_s > 0.1 THEN scan_s := 0.01; END_IF;

sp_mms := INT_TO_REAL(cfg_belt_mms);
IF sp_mms < 20.0 OR sp_mms > 590.0 THEN sp_mms := 120.0; END_IF;

(* analog scaling *)
height_mm := INT_TO_REAL(height_raw) * height_max / raw_max;
weight_g  := INT_TO_REAL(weight_raw) * weight_max / raw_max;
speed_mms := INT_TO_REAL(speed_fb_raw) * speed_max / raw_max;

(* tacho fallback: if commanded to run but feedback reads zero, use the   *)
(* setpoint so position tracking keeps working with a missing sensor.     *)
IF belt_run AND speed_mms < 5.0 THEN
  speed_mms := sp_mms;
END_IF;
IF NOT belt_run THEN
  speed_mms := 0.0;
END_IF;


(* ==================================================================== *)
(*  2 . state machine                                                    *)
(* ==================================================================== *)

CASE state OF
  0: (* INIT *)
    belt_run := FALSE;
    IF estop_chain THEN
      state := 1;
    ELSE
      state := 4;
    END_IF;

  1: (* IDLE *)
    belt_run := FALSE;
    IF trig_start.q AND estop_chain THEN
      jam_s := 0.0;
      quiet_s := 0.0;
      state := 2;
      horn_s := 0.5;      (* start blip *)
    END_IF;

  2: (* RUN *)
    belt_run := TRUE;
    IF NOT estop_chain THEN
      state := 4;
    ELSIF jam_latched THEN
      state := 3;
    ELSIF trig_stop.q THEN
      state := 1;
    END_IF;

  3: (* JAM - belt stopped, horn steady, wait for manual reset *)
    belt_run := FALSE;
    horn_on := TRUE;
    IF trig_start.q AND estop_chain THEN
      jam_latched := FALSE;
      horn_on := FALSE;
      state := 1;
    END_IF;

  4: (* ESTOP - everything off, latched until chain healthy + start *)
    belt_run := FALSE;
    IF estop_chain AND trig_start.q THEN
      estop_latched := FALSE;
      jam_latched := FALSE;
      state := 1;
    END_IF;
END_CASE;

IF (state = 2) THEN
  run_s := run_s + scan_s;
ELSIF (state = 3) OR (state = 4) THEN
  down_s := down_s + scan_s;
END_IF;


(* ==================================================================== *)
(*  3 . piece tracking                                                   *)
(* ==================================================================== *)

(* new piece on the photo-eye rising edge *)
IF trig_pe.q AND (state = 2) THEN
  i := -1;
  FOR d := 0 TO 15 DO
    IF NOT pieces[d].active AND i < 0 THEN i := d; END_IF;
  END_FOR;
  IF i >= 0 THEN
    pieces[i].active  := TRUE;
    pieces[i].pos     := 0.0;
    pieces[i].height  := 0.0;
    pieces[i].metal   := FALSE;
    pieces[i].weight  := 0.0;
    pieces[i].verdict := 0;
    pieces[i].routed  := FALSE;
    pieces[i].id_done := FALSE;
    pieces[i].lc_done := FALSE;
    c_detect := c_detect + 1;
    detect_tot := detect_tot + 1.0;
  ELSE
    tracker_full := TRUE;
  END_IF;
END_IF;

(* propagate, measure, decide *)
FOR i := 0 TO 15 DO
  IF pieces[i].active AND NOT pieces[i].routed THEN
    pieces[i].pos := pieces[i].pos + speed_mms * scan_s;

    (* HS - track the max height across the curtain window *)
    IF (pieces[i].pos >= hs_pos) AND (pieces[i].pos < hs_pos + hs_win) THEN
      IF height_mm > pieces[i].height THEN
        pieces[i].height := height_mm;
      END_IF;
    END_IF;

    (* ID - latch the metal bit on the crossing scan *)
    IF (NOT pieces[i].id_done) AND (pieces[i].pos >= id_pos) THEN
      pieces[i].metal := id_met;
      pieces[i].id_done := TRUE;
    END_IF;

    (* LC - track the max weight across the cell window, then decide *)
    IF (pieces[i].pos >= lc_pos) AND (pieces[i].pos < lc_pos + lc_win) THEN
      IF weight_g > pieces[i].weight THEN
        pieces[i].weight := weight_g;
      END_IF;
    END_IF;
    IF NOT pieces[i].lc_done AND pieces[i].pos >= lc_pos + lc_win THEN
      IF pieces[i].height >= cfg_tall THEN
        pieces[i].verdict := 3;
      ELSIF pieces[i].metal THEN
        pieces[i].verdict := 2;
      ELSIF (pieces[i].weight < cfg_min) OR (pieces[i].weight > cfg_max) THEN
        pieces[i].verdict := 4;
      ELSE
        pieces[i].verdict := 1;
      END_IF;
      pieces[i].lc_done := TRUE;
    END_IF;

    (* end of belt without a divert - missed piece *)
    IF pieces[i].pos > belt_len THEN
      pieces[i].active := FALSE;
      missed := missed + 1;
    END_IF;
  END_IF;
END_FOR;


(* ==================================================================== *)
(*  4 . diverters                                                        *)
(* ==================================================================== *)

(* Each gate: arm the solenoid prearm_mm before the piece arrives, hold   *)
(* until the confirm photo-eye or a timeout, then count it and free the   *)
(* slot. The reject pusher confirms on the chute photo-eye.               *)
div_l1 := FALSE;
div_l2 := FALSE;
div_l3 := FALSE;
div_rj := FALSE;

IF state = 2 THEN
  FOR i := 0 TO 15 DO
    IF pieces[i].active AND NOT pieces[i].routed AND pieces[i].verdict > 0 THEN
      fired := FALSE;
      gate_end := 0.0;
      cfm := gate_confirm;

      CASE pieces[i].verdict OF
        1: IF pieces[i].pos >= g_l1 - prearm THEN div_l1 := TRUE; fired := TRUE; gate_end := g_l1; END_IF;
        2: IF pieces[i].pos >= g_l2 - prearm THEN div_l2 := TRUE; fired := TRUE; gate_end := g_l2; END_IF;
        3: IF pieces[i].pos >= g_l3 - prearm THEN div_l3 := TRUE; fired := TRUE; gate_end := g_l3; END_IF;
        4: IF pieces[i].pos >= g_rj - prearm THEN div_rj := TRUE; fired := TRUE; gate_end := g_rj;
             cfm := gate_confirm OR chute_pe;
           END_IF;
      END_CASE;

      IF fired AND (cfm OR pieces[i].pos > gate_end + 300.0) THEN
        pieces[i].routed := TRUE;
        pieces[i].active := FALSE;
        c_routed := c_routed + 1;
        route_tot := route_tot + 1.0;
        buckets[bucket_i] := buckets[bucket_i] + 1;
        CASE pieces[i].verdict OF
          1: c_l1 := c_l1 + 1;
          2: c_l2 := c_l2 + 1;
          3: c_l3 := c_l3 + 1;
          4: c_rj := c_rj + 1;
        END_CASE;
      END_IF;
    END_IF;
  END_FOR;
END_IF;


(* ==================================================================== *)
(*  5 . watchdogs                                                        *)
(* ==================================================================== *)

IF state = 2 THEN
  (* jam: photo-eye blocked longer than the limit while running *)
  IF pe THEN
    jam_s := jam_s + scan_s;
    IF jam_s >= jam_lim THEN
      jam_latched := TRUE;
    END_IF;
  ELSE
    jam_s := 0.0;
  END_IF;

  (* stall: running but nothing new arrives - alarm only, belt keeps going *)
  IF trig_pe.q THEN
    quiet_s := 0.0;
    stall_on := FALSE;
  ELSE
    quiet_s := quiet_s + scan_s;
  END_IF;
  IF quiet_s > 20.0 THEN stall_on := TRUE; END_IF;
ELSE
  jam_s := 0.0;
  quiet_s := 0.0;
  stall_on := FALSE;
END_IF;

(* tracker status: full only when no free slot exists *)
tracker_full := TRUE;
FOR i := 0 TO 15 DO
  IF NOT pieces[i].active THEN tracker_full := FALSE; END_IF;
END_FOR;


(* ==================================================================== *)
(*  6 . alarm word                                                       *)
(* ==================================================================== *)

alarm_w := 0;
IF jam_latched THEN   alarm_w := alarm_w OR 1; END_IF;
IF estop_latched THEN alarm_w := alarm_w OR 2; END_IF;
IF NOT estop_chain THEN alarm_w := alarm_w OR 4; END_IF;
IF stall_on THEN      alarm_w := alarm_w OR 8; END_IF;
IF tracker_full THEN  alarm_w := alarm_w OR 16; END_IF;


(* ==================================================================== *)
(*  7 . OEE                                                              *)
(* ==================================================================== *)

(* rolling pieces per minute from the 60 one-second buckets *)
ppm_acc := 0;
FOR i := 0 TO 59 DO
  ppm_acc := ppm_acc + buckets[i];
END_FOR;
ppm := ppm_acc;

(* A = run / (run + down) *)
IF (run_s + down_s) > 1.0 THEN
  avail := run_s / (run_s + down_s);
ELSE
  avail := 1.0;
END_IF;

(* P = rolling rate / ideal, capped *)
perf := INT_TO_REAL(ppm_acc) / ideal_rate;
IF perf > 1.0 THEN perf := 1.0; END_IF;

(* Q = routed / detected *)
IF detect_tot > 0.0 THEN
  qual := route_tot / detect_tot;
ELSE
  qual := 1.0;
END_IF;

a10 := REAL_TO_INT(avail * 1000.0);
p10 := REAL_TO_INT(perf * 1000.0);
q10 := REAL_TO_INT(qual * 1000.0);


(* ==================================================================== *)
(*  8 . outputs and telemetry                                            *)
(* ==================================================================== *)

lamp_g := (state = 2) AND (alarm_w = 0);
lamp_a := (state = 1) OR (state = 0);
lamp_r := (state = 3) OR (state = 4);
horn := horn_on;

(* horn pulse on start *)
IF horn_s > 0.0 THEN
  horn_s := horn_s - scan_s;
  IF horn_s > 0.0 THEN horn := TRUE; END_IF;
END_IF;

(* speed setpoint and echo *)
sp_raw := REAL_TO_INT(sp_mms * raw_max / speed_max);
speed_echo := REAL_TO_INT(speed_mms);

(* heartbeat: one tick per second - HMI watches this to detect a frozen PLC *)
hb_acc := hb_acc + scan_s;
IF hb_acc >= 1.0 THEN
  hb_acc := hb_acc - 1.0;
  heartbeat := heartbeat + 1;
  IF heartbeat > 32000 THEN heartbeat := 0; END_IF;
END_IF;

state_w := state;
version_w := 101;

END_PROGRAM
