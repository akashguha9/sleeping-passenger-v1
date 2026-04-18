# IMPROV_LAYER (IL)
# Module: S4 — Middle gear between LEAVE and FIRE_MODE
# Added: April 17 2026
# Source: Soliloquy / metacognition / wisdom / angel-devil / paradox / improv session
#
# The pipeline previously had two gears: FIRE_MODE (full entry) and LEAVE (binary no).
# IL adds a middle gear: named adaptive action policies for signals that are genuine
# but not clean enough for FIRE_MODE and too interesting to LEAVE.
#
# Three gears:
#   LEAVE:     SINK/TRAP/VETO or CFD LOCKED. Binary no. No capital.
#   IL:        WEAK/NEUTRAL + MOD/LOW + EMERGING/CONVERGING + novelty/divergence.
#              PROBE / STAGGER / SANDBOX / DELAY / RESIZE
#   FIRE_MODE: SBE STRONG_FLOAT + ASS HIGH + CFD CONVERGING. Full QUARTER_UNIT.
#
# IL trigger (all 4 conditions required):
#   1. SBE B_state IN ('WEAK_FLOAT', 'NEUTRAL')        — not STRONG_FLOAT
#   2. ASS Q_state IN ('MODERATE', 'LOW')              — not HIGH quality
#   3. CFD cfd_state IN ('EMERGING', 'CONVERGING')     — slope rising (not LOCKED)
#   4. novelty_flag = True OR EDS_state = 'STRONG_DIVERGE'
#
# IL adaptive actions:
#
#   PROBE:
#     Size: HALF_QUARTER_UNIT (50% of minimum position size)
#     observation_window: 3-5 days
#     invalidation: same as BRANCH_PAYLOAD but tighter (stop at -7% vs -10%)
#     improv rule: 'yes-and without commitment — small bet while signal develops'
#     trigger: SBE WEAK_FLOAT + ASS MODERATE + CFD CONVERGING
#
#   STAGGER:
#     Split QUARTER_UNIT into 3 tranches timed to pipeline gate progression:
#       tranche_1 (1/3): enter NOW when CFD EMERGING + dCS/dt rising
#       tranche_2 (1/3): enter when CFD -> CONVERGING (next scan window)
#       tranche_3 (1/3): enter when SBE -> STRONG_FLOAT (signal strengthens)
#     improv rule: 'follow energy as it arrives — each tranche earns the next'
#     trigger: SBE WEAK_FLOAT + ASS MODERATE + CFD EMERGING
#     portfolio note: SGOL April 16 = correct IL STAGGER (first tranche justified)
#
#   SANDBOX:
#     Paper trade only. No real capital deployed.
#     Outcome logged toward MW calibration weight.
#     Does NOT count toward T-count (T=6→10 requires real capital closed trades).
#     improv rule: 'stay present without capital risk — improv rehearsal'
#     trigger: ASS S < 0.30 (VETO) BUT CFD CONVERGING + SBE WEAK_FLOAT
#     portfolio note: JPM CHAOS_ENTRY would have been SANDBOX — no real capital
#
#   DELAY:
#     Wait one full CFD scan window (12-24h) before re-evaluating.
#     improv rule: 'the scene is still forming — do not rush the first line'
#     trigger: CFD EMERGING + dCS/dt < CFD_DCDT_TRIGGER threshold
#     action: set review_at = now + 24h, re-run full pipeline at review_at
#
#   RESIZE:
#     Size: EIGHTH_UNIT (half of PROBE, quarter of QUARTER_UNIT)
#     Maximum ambiguity state.
#     improv rule: 'minimum viable signal bet under maximum uncertainty'
#     trigger: SBE NEUTRAL + ASS LOW + novel_pattern_flag = True
#
# Portfolio retrospectives:
#   SGOL April 16:
#     SBE WEAK_FLOAT (B ≈ +0.30), ASS MODERATE (Q ≈ 0.55, new instrument),
#     CFD CONVERGING (Iran/war consensus), novelty flag (new gold proxy)
#     IL -> STAGGER -> tranche_1 QUARTER_UNIT justified. Entry .74.
#     +7.2% unrealised. Hard stop .17. Correct IL action confirmed.
#
#   JPM CHAOS_ENTRY:
#     SBE NEUTRAL, ASS LOW (Q < 0.36), CFD LOCKED (dCS/dt ≈ 0)
#     CFD LOCKED -> IL trigger condition 3 FAILS -> route to LEAVE or SANDBOX
#     IL SANDBOX: paper only, no real capital.
#     Actual: entered CHAOS_ENTRY without pipeline gate.
#     IL would have prevented consequence_persistence=2.5 DEGRADED state.
#
# The improv law:
#   LEAVE and FIRE_MODE are two gears. IL is the middle gear.
#   Not every signal is binary. Some signals say 'yes-and' not 'yes' or 'no'.
#   'Don't break the scene' -> preserve coherence while adapting.
#   'Follow energy' -> STAGGER tranches follow CFD/SBE progression.
#   Mistakes in PROBE/STAGGER become calibration data, not CHAOS_ENTRY violations.

IL_PROBE_SIZE   = 0.50   # fraction of QUARTER_UNIT (half)
IL_RESIZE_SIZE  = 0.25   # fraction of QUARTER_UNIT (quarter)
IL_STAGGER_N    = 3      # number of tranches
IL_SANDBOX_CAPITAL = 0.0 # no real capital in SANDBOX mode
IL_OBSERVATION_DAYS = 3  # minimum observation window for PROBE

def il_trigger_check(sbe_b_state: str, ass_q_state: str,
                     cfd_state: str, novelty_flag: bool,
                     eds_state: str) -> dict:
    conditions = {
        'sbe_weak_or_neutral': sbe_b_state in ('WEAK_FLOAT', 'NEUTRAL'),
        'ass_mod_or_low':      ass_q_state in ('MODERATE', 'LOW'),
        'cfd_not_locked':      cfd_state in ('EMERGING', 'CONVERGING'),
        'novel_or_diverge':    novelty_flag or eds_state == 'STRONG_DIVERGE',
    }
    il_triggered = all(conditions.values())
    return {'il_triggered': il_triggered, 'conditions': conditions}

def select_il_action(sbe_b_state: str, ass_q_state: str,
                     cfd_state: str, ass_s_score: float,
                     cfd_dcdt: float, cfd_dcdt_trigger: float = 0.08,
                     novel_flag: bool = False) -> dict:
    # SANDBOX: parachute not attached but scene is forming
    if ass_s_score < 0.30 and cfd_state in ('EMERGING', 'CONVERGING'):
        return {
            'il_action':      'SANDBOX',
            'size_fraction':  IL_SANDBOX_CAPITAL,
            'counts_toward_t': False,
            'counts_toward_cal': True,
            'note':           'SANDBOX: no capital, logs toward CAL. Yes-and rehearsal.',
        }
    # DELAY: scene still forming, slope below trigger
    if cfd_dcdt < cfd_dcdt_trigger and cfd_state == 'EMERGING':
        return {
            'il_action':      'DELAY',
            'size_fraction':  0.0,
            'wait_hours':     24,
            'note':           'DELAY: scene forming. Wait one CFD scan window.',
        }
    # RESIZE: maximum ambiguity
    if sbe_b_state == 'NEUTRAL' and ass_q_state == 'LOW' and novel_flag:
        return {
            'il_action':      'RESIZE',
            'size_fraction':  IL_RESIZE_SIZE,
            'note':           'RESIZE: minimum viable bet. Maximum ambiguity.',
        }
    # STAGGER: EMERGING slope rising — split entry
    if cfd_state == 'EMERGING' and cfd_dcdt >= cfd_dcdt_trigger:
        return {
            'il_action':      'STAGGER',
            'size_fraction':  IL_PROBE_SIZE,
            'tranches':       IL_STAGGER_N,
            'tranche_1_now':  1/3,
            'tranche_2_on':   'CFD_CONVERGING',
            'tranche_3_on':   'SBE_STRONG_FLOAT',
            'note':           'STAGGER: follow energy. Each tranche earns the next.',
        }
    # PROBE: CONVERGING but not yet STRONG_FLOAT — small bet
    if cfd_state == 'CONVERGING':
        return {
            'il_action':      'PROBE',
            'size_fraction':  IL_PROBE_SIZE,
            'observation_days': IL_OBSERVATION_DAYS,
            'note':           'PROBE: yes-and. Small bet while signal develops.',
        }
    # Default: LEAVE (should not reach here if trigger_check passed)
    return {'il_action': 'LEAVE', 'size_fraction': 0.0, 'note': 'IL default: LEAVE.'}

def il_full_check(sbe_b_state: str, ass_q_state: str, ass_s_score: float,
                  cfd_state: str, cfd_dcdt: float, eds_state: str,
                  novelty_flag: bool = False) -> dict:
    trigger = il_trigger_check(sbe_b_state, ass_q_state, cfd_state, novelty_flag, eds_state)
    if not trigger['il_triggered']:
        return {
            'il_triggered': False,
            'route':        'LEAVE' if sbe_b_state in ('SINK','TRAP') else 'FIRE_MODE_CHECK',
            'note':         'IL not triggered. Standard gate routing applies.',
        }
    action = select_il_action(sbe_b_state, ass_q_state, cfd_state, ass_s_score,
                               cfd_dcdt, novelty_flag=novelty_flag)
    return {
        'il_triggered':   True,
        'il_action':      action['il_action'],
        'size_fraction':  action['size_fraction'],
        'conditions':     trigger['conditions'],
        'action_details': action,
    }
