\# Narrative Intent / Hook-Distort-Trap Freeze Addendum



\## 1. Freeze Status



\*\*Status: freeze-ready with conditions\*\*



The Narrative Intent track is no longer draft-only. It already has:



\- a bounded system spec in `docs/architecture/narrative\_intent\_system\_spec.md`

\- concrete output schemas in `schemas/narrative\_intent/`

\- a cross-domain example file

\- the original reflection in research docs



What remained was not a new framework, but a tightening pass on:



\- score separation

\- output object responsibility boundaries

\- domain-adapter rules

\- repo integration boundary

\- schema-shaped examples



With this addendum, the architecture should be treated as frozen for documentation purposes. The next milestone is not code. The next milestone is a \*\*schema-and-examples freeze\*\*.



\---



\## 2. Tightened Score Definitions



\### Hook Score

\*\*Purpose:\*\* measure how strong the narrative’s attention anchor is before contradiction or behavioral inference.



\*\*Depends on:\*\*

\- authority cues

\- familiarity

\- aesthetic strength

\- status signaling

\- trust frame

\- container credibility



\*\*Must not depend on:\*\*

\- distortion

\- beneficiary mapping

\- target behavior

\- timing

\- downstream engagement counts



\*\*High means:\*\* the artifact enters through a strong, credible, socially legible frame.  

\*\*Low means:\*\* the artifact lacks a compelling or trusted anchor.  

\*\*Misuse warning:\*\* high hook is not evidence of manipulation; it only says the entrance frame is strong.



\---



\### Distortion Score

\*\*Purpose:\*\* measure how much the content departs from its frame, evidence base, or expected coherence.



\*\*Depends on:\*\*

\- contradiction markers

\- omission

\- simplification

\- incongruity

\- frame-content mismatch

\- identity disruption

\- evidence baseline where available



\*\*Must not depend on:\*\*

\- target behavior

\- beneficiary certainty

\- timing

\- trap participation effects



\*\*High means:\*\* the message materially bends, compresses, or destabilizes the frame it is using.  

\*\*Low means:\*\* the message is largely consistent with its frame and evidence context.  

\*\*Misuse warning:\*\* high distortion does not imply malice; protective and stabilizing narratives can also distort.



\---



\### Trap Score

\*\*Purpose:\*\* measure how strongly the artifact creates unresolved interpretation pressure.



\*\*Depends on:\*\*

\- ambiguity score

\- closure deficit

\- forced participation

\- unresolved binary structure

\- identity-instability contribution



\*\*Must not depend on:\*\*

\- beneficiary mapping

\- timing

\- market/event outcome



\*\*High means:\*\* the artifact forces the audience into interpretation without closure.  

\*\*Low means:\*\* the artifact resolves cleanly and does not require ongoing inference.  

\*\*Misuse warning:\*\* ambiguity alone is not enough; not every ambiguous message is a trap.



\---



\### Identity Instability Score

\*\*Purpose:\*\* measure how unstable the actor/persona interpretation is inside the artifact.



\*\*Depends on:\*\*

\- count of plausible identity labels

\- role conflict

\- presentation mismatch

\- contradictory persona cues



\*\*Must not depend on:\*\*

\- general message ambiguity unrelated to actor identity

\- timing

\- beneficiary mapping



\*\*High means:\*\* the audience cannot settle on a stable reading of who the actor is.  

\*\*Low means:\*\* the actor/persona is legible and stable.  

\*\*Misuse warning:\*\* only use this where an interpretable actor/persona is actually present.



\---



\### Intent Score

\*\*Purpose:\*\* measure how strongly the narrative appears to be pushing a target behavior.



\*\*Depends on:\*\*

\- distortion pattern

\- direction strength

\- target-behavior clarity

\- trust/simplification context



\*\*Must not depend on:\*\*

\- beneficiary certainty

\- timing precision

\- readiness state

\- action-engine outcomes



\*\*High means:\*\* the narrative appears purposefully directional rather than merely expressive or descriptive.  

\*\*Low means:\*\* the narrative lacks clear behavioral push.  

\*\*Misuse warning:\*\* intent score is not proof of centrally designed intent; emergent narratives can still be directional.



\---



\### Narrative Intent Score

\*\*Purpose:\*\* synthesize whether the artifact functions as a likely behavior-coordination narrative.



\*\*Depends on:\*\*

\- intent score

\- timing score

\- beneficiary clarity

\- behavioral impact estimate

\- class consistency



\*\*Must not depend on:\*\*

\- portfolio results

\- readiness scores

\- friction scores

\- action decisions



\*\*High means:\*\* the narrative is plausibly directional, well-timed, and behaviorally meaningful.  

\*\*Low means:\*\* the narrative is mostly informational, noisy, weakly timed, or weakly directional.  

\*\*Misuse warning:\*\* this is a probabilistic synthesis score, not a claim of proven motive.



\---



\### Signal Conflict Score

\*\*Purpose:\*\* measure tension between a dominant narrative and contradictory evidence or structure.



\*\*Depends on:\*\*

\- dominant-frame strength

\- contradiction strength

\- evidence conflict

\- cross-context disagreement



\*\*Must not depend on:\*\*

\- engagement volume

\- beneficiary mapping

\- trap mechanics



\*\*High means:\*\* strong narrative and strong contradiction coexist.  

\*\*Low means:\*\* the narrative and available evidence largely align.  

\*\*Misuse warning:\*\* this score only works where an evidence baseline exists; it is weak in sparse interpersonal contexts.



\---



\### Meme Signal Score

\*\*Purpose:\*\* measure the potency of the artifact specifically as a hook-distort-trap object.



\*\*Depends on:\*\*

\- hook score

\- distortion score

\- trap score



\*\*Must not depend on:\*\*

\- beneficiary inference

\- timing precision

\- policy/repo state

\- domain outcomes



\*\*High means:\*\* the artifact is structurally strong for attention capture and retention.  

\*\*Low means:\*\* one or more of the hook-distort-trap components is weak.  

\*\*Misuse warning:\*\* do not confuse meme potency with truth, importance, or trade edge.



\---



\## 3. Tightened Output Object Contracts



\### HookReport

\*\*Exact purpose:\*\* record only the strength and composition of the attention anchor.



\*\*Essential fields:\*\*

\- `artifact\_id`

\- `domain`

\- `hook\_score`

\- `anchor\_type`

\- `anchor\_summary`

\- `components`



\*\*Optional / deferred:\*\*

\- `notes`

\- deeper attribution detail



\*\*Must never include:\*\*

\- beneficiary claims

\- target behavior

\- timing claims

\- motive labels

\- readiness/policy/action implications



\*\*Relationship to other objects:\*\*

\- upstream structural input to `DistortionReport`, `TrapReport`, and `NarrativeIntentReport`

\- must stay narrow and not absorb later-layer synthesis



\---



\### DistortionReport

\*\*Exact purpose:\*\* record how the narrative departs from its frame, evidence, or expected coherence.



\*\*Essential fields:\*\*

\- `artifact\_id`

\- `domain`

\- `distortion\_score`

\- `distortion\_types`

\- `frame\_content\_mismatch`

\- `summary`



\*\*Optional / deferred:\*\*

\- `functional\_role\_hint`

\- `notes`



\*\*Must never include:\*\*

\- final motive conclusion

\- target behavior as if already established

\- timing explanation

\- beneficiary map

\- repo action or risk recommendations



\*\*Relationship to other objects:\*\*

\- should feed `TrapReport` and `NarrativeIntentReport`

\- `functional\_role\_hint` stays a hint, not a replacement for final intent synthesis



\---



\### TrapReport

\*\*Exact purpose:\*\* record whether the artifact creates unresolved participation pressure and identity ambiguity.



\*\*Essential fields:\*\*

\- `artifact\_id`

\- `domain`

\- `trap\_score`

\- `ambiguity\_score`

\- `closure\_deficit`

\- `identity\_instability\_score`

\- `summary`



\*\*Optional / deferred:\*\*

\- `forced\_participation`

\- `plausible\_identity\_labels`

\- `interpretability\_band`

\- `notes`



\*\*Must never include:\*\*

\- beneficiary certainty

\- target behavior claims

\- timing claims

\- action/routing implications



\*\*Relationship to other objects:\*\*

\- remains an attention/retention object

\- can inform `NarrativeIntentReport`, but must not become the intent report



\---



\### NarrativeIntentReport

\*\*Exact purpose:\*\* provide the synthesis output for narrative class, directional behavior, timing relevance, and beneficiary likelihood.



\*\*Essential fields:\*\*

\- `artifact\_id`

\- `domain`

\- `primary\_class`

\- `hook\_score`

\- `distortion\_score`

\- `trap\_score`

\- `intent\_score`

\- `narrative\_intent\_score`

\- `target\_behavior`

\- `timing\_score`

\- `beneficiary\_confidence`

\- `summary`



\*\*Optional / deferred:\*\*

\- `secondary\_class`

\- `signal\_conflict\_score`

\- `likely\_beneficiaries`

\- `why\_now\_summary`

\- `risk\_flags`

\- `notes`



\*\*Must never include:\*\*

\- readiness score changes

\- friction changes

\- policy changes

\- action commands

\- trade routing

\- tag emissions



\*\*Relationship to other objects:\*\*

\- synthesis layer over `HookReport`, `DistortionReport`, and `TrapReport`

\- should reference lower-level structure semantically, not duplicate every lower-level detail



\---



\## 4. Tightened Domain Adapter Rules



\### Markets

\*\*Reuse unchanged:\*\*

\- hook/distort/trap logic

\- signal conflict

\- timing

\- beneficiary mapping

\- narrative classing



\*\*Mandatory context:\*\*

\- event timeline

\- price move context

\- prior narrative state

\- regime / positioning backdrop

\- source class



\*\*Naive mistake to avoid:\*\*

\- treating strong hook or meme potency as trade edge

\- treating late-stage distribution language as early structural signal



\*\*Especially useful outputs:\*\*

\- `DistortionReport`

\- `NarrativeIntentReport`

\- `SignalConflictScore`

\- timing and beneficiary summaries



\---



\### Social Media

\*\*Reuse unchanged:\*\*

\- hook/distort/trap

\- identity instability

\- meme signal

\- target-behavior estimation



\*\*Mandatory context:\*\*

\- platform/container type

\- visual framing where present

\- engagement setting

\- creator/source posture



\*\*Naive mistake to avoid:\*\*

\- reading virality as proof of deliberate intent

\- assuming irony and satire are easy to classify



\*\*Especially useful outputs:\*\*

\- `HookReport`

\- `TrapReport`

\- `MemeSignalScore`

\- `NarrativeIntentReport` when recruitment or confusion/masking is suspected



\---



\### Football Messaging

\*\*Reuse unchanged:\*\*

\- trust/simplify/guide/behavior stack

\- timing

\- beneficiary mapping

\- functional distortion logic



\*\*Mandatory context:\*\*

\- club state

\- media pressure

\- match or transfer timing

\- official vs unofficial source

\- stakeholder map



\*\*Naive mistake to avoid:\*\*

\- assuming all official statements are exploitative

\- assuming all calming statements are truthful



\*\*Especially useful outputs:\*\*

\- `DistortionReport`

\- `NarrativeIntentReport`

\- timing analysis

\- stabilizing / protective / confusion-masking classification



\---



\### Interpersonal

\*\*Reuse unchanged:\*\*

\- functional distortion logic

\- target behavior estimation

\- timing relevance

\- beneficiary reasoning



\*\*Mandatory context:\*\*

\- relationship context

\- recent prior state

\- stakes

\- conversational sequence

\- known constraints or vulnerabilities



\*\*Naive mistake to avoid:\*\*

\- overclaiming intent or beneficiary certainty from sparse evidence

\- treating every simplification as manipulation



\*\*Especially useful outputs:\*\*

\- `DistortionReport`

\- `NarrativeIntentReport`

\- low-certainty beneficiary framing

\- timing and direction summaries



\---



\## 5. Frozen Repo Integration Boundary



\### Where this layer can live

Architecture/docs remain under:

\- `docs/architecture/narrative\_intent\_system\_spec.md`

\- `docs/architecture/narrative\_intent\_freeze\_addendum.md`

\- `docs/research/narrative\_intent\_hook\_distort\_trap\_reflection.md`

\- `docs/examples/narrative\_intent\_cross\_domain\_examples.md`

\- `schemas/narrative\_intent/\*.schema.json`



If code ever arrives later, it should live in a dedicated namespace such as:

\- `scripts/narrative\_intent/`



It must not start as more flat root-level one-off scripts.



\### What it may eventually feed

\- a standalone narrative analytics report generator

\- upstream research/enrichment artifacts

\- optional feature generation for future models

\- a future optional orchestrated analysis pass



\### What it must not directly modify

\- `scripts/tag\_engine.py`

\- readiness logic in `scripts/pipeline\_health\_report.py`

\- friction logic in `scripts/blocker\_cost\_engine.py`

\- policy logic in the current SCM/policy path

\- action selection in `scripts/action\_engine.py`



\### Operational stance

\- near-term: standalone only

\- mid-term: optional orchestrated pass at most

\- long-term: feature supplier to other systems after validation



\### Frozen integration rule

This layer may emit structured analytics outputs.  

Other systems may later choose to consume them.  

This layer must not directly rewrite current diagnostics, scoring, gating, or action paths.



\---



\## 6. Next Non-Coding Milestone



\*\*Milestone: schema-and-examples freeze\*\*



Best next step:

\- keep the current spec and schemas

\- add one schema-shaped example pack that instantiates:

&#x20; - `HookReport`

&#x20; - `DistortionReport`

&#x20; - `TrapReport`

&#x20; - `NarrativeIntentReport`

\- cover exactly the four current adapters:

&#x20; - markets

&#x20; - social\_media

&#x20; - football\_messaging

&#x20; - interpersonal



\### Why this is the best next step

\- the architecture is already bounded

\- the remaining risk is drift between prose, schemas, and examples

\- schema-shaped examples will force:

&#x20; - score separation

&#x20; - output discipline

&#x20; - domain-adapter realism

\- it is finite and reviewable



\---



\## 7. What Not To Build Yet



\- Do not build `scripts/narrative\_intent/` detector modules yet.

\- Do not wire anything into `run\_diagnostics\_pipeline.py`.

\- Do not add anything to `tag\_engine.py`.

\- Do not add narrative-derived fields to tagging-v1 schemas.

\- Do not feed these scores into readiness logic.

\- Do not feed these scores into friction logic.

\- Do not feed these scores into policy logic.

\- Do not feed these scores into `action\_engine.py`.

\- Do not build a beneficiary graph engine with hard certainty claims.

\- Do not build model calibration or learned ranking pipelines yet.

\- Do not create new flat root scripts for each detector.

\- Do not turn the system into sentiment analysis with renamed labels.

\- Do not add domain-general claims that bypass the current adapters.



\---



\## 8. Final Verdict



\### Update next

Update:

\- `docs/architecture/narrative\_intent\_system\_spec.md`



with the tightened definitions from this addendum.



\### Add next artifact

Add:

\- `docs/examples/narrative\_intent\_contract\_examples.md`



That file should contain four schema-bound examples, one per current domain adapter, using the existing report schemas.



\### Must not happen next

\- do not build detector code

\- do not integrate this track into `tag\_engine.py`

\- do not connect it to readiness, friction, policy, or action selection yet

