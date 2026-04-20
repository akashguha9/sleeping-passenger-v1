\# Narrative Intent / Hook-Distort-Trap System Spec



\## 1. Purpose



This document defines a future analytics layer for detecting and structuring:



\- hook / attention anchors

\- distortion / contradiction

\- ambiguity / trap structure

\- behavioral direction

\- timing relevance

\- beneficiary mapping

\- narrative intent



This layer is separate from:



\- readiness scoring

\- friction scoring

\- policy logic

\- action execution

\- tagging-v1 operational memory



It is an analysis layer, not an execution layer.



\---



\## 2. System Boundary



\### In scope

This system is responsible for:



\- analyzing a narrative artifact or message

\- identifying the attention anchor

\- identifying distortion or frame-content mismatch

\- identifying ambiguity / forced participation structure

\- estimating behavioral direction

\- estimating likely beneficiary set

\- estimating timing relevance

\- producing structured narrative-intent outputs



\### Out of scope

This system is not responsible for:



\- changing trade execution

\- changing readiness scores

\- changing policy states

\- changing friction math

\- changing action engine routing

\- storing operational tags for v1 tagging

\- making deterministic trading decisions



\### Relationship to current repo

This system may later integrate as:



\- an upstream research/enrichment module

\- a separate report generator

\- a feature generator for future models

\- an optional orchestrated analysis pass



It must not be folded into `tag\\\_engine.py` or current health/action modules.



\---



\## 3. Core Design Principle



Narratives are treated as behavior coordination systems, not merely information objects.



The system separates:



1\. \*\*Attention layer\*\*

&#x20;  - Hook

&#x20;  - Distortion

&#x20;  - Ambiguity / Trap



2\. \*\*Control layer\*\*

&#x20;  - Direction

&#x20;  - Timing

&#x20;  - Beneficiary

&#x20;  - Intent



Core stack:



\*\*Hook -> Distort -> Trap -> Direction -> Timing -> Beneficiary -> Intent\*\*



\---



\## 4. Canonical Input Bundle



Every evaluation should be based on a normalized input bundle.



\### Required fields

\- `artifact\\\_id`: stable identifier for the evaluated artifact

\- `domain`: one of `markets`, `social\\\_media`, `football\\\_messaging`, `interpersonal`

\- `content\\\_type`: one of `text`, `image\\\_text`, `statement`, `post`, `headline`, `caption`

\- `surface\\\_text`: raw text or extracted text

\- `timestamp\\\_utc`: timestamp of publication or observation

\- `source\\\_label`: human-readable source name



\### Optional fields

\- `image\\\_context`: structured notes about visual framing

\- `author\\\_actor`: who produced the narrative

\- `target\\\_audience`: intended audience if known

\- `event\\\_context`: related event, shock, or system condition

\- `market\\\_context`: price move / sentiment backdrop where relevant

\- `reply\\\_context`: comments / reactions / engagement summary

\- `trust\\\_context`: why the source may be believed

\- `prior\\\_state\\\_summary`: relevant state before the narrative appeared



\---



\## 5. Core Modules



\## 5.1 Hook Detector

Purpose:

Detect the clean attention anchor.



Looks for:

\- authority

\- status

\- familiarity

\- aesthetic strength

\- legitimacy cues

\- social proof

\- dominant consensus framing



Output:

\- hook score

\- hook components

\- anchor summary



\---



\## 5.2 Distortion Detector

Purpose:

Detect contradiction, mismatch, simplification, taboo insertion, or frame-content inconsistency.



Looks for:

\- contradiction inside a credible frame

\- omission

\- absurdity

\- content-frame mismatch

\- compression that changes meaning

\- simplification with behavioral effect



Output:

\- distortion score

\- distortion type(s)

\- distortion summary



\---



\## 5.3 Ambiguity / Trap Detector

Purpose:

Detect unresolved structures that force participation and delay closure.



Looks for:

\- unresolved binaries

\- “truth and a lie” structures

\- forced interpretation

\- closure deficit

\- socially strange alternatives

\- unresolved classification pressure



Output:

\- trap score

\- ambiguity score

\- closure deficit note



\---



\## 5.4 Identity Instability Tracker

Purpose:

Measure whether the subject remains unresolved across multiple plausible identities.



Looks for:

\- conflicting persona labels

\- unstable interpretation

\- irony / sincerity ambiguity

\- confidence / insecurity ambiguity

\- self-aware / delusional ambiguity



Output:

\- identity instability score

\- plausible identity labels

\- instability explanation



\---



\## 5.5 Functional Distortion Classifier

Purpose:

Classify distortion by role rather than truth value alone.



Core classes:

\- `pure\\\_signal`

\- `noise`

\- `engineered\\\_narrative`

\- `stabilizing`

\- `protective`

\- `exploitative`

\- `motivational`

\- `emergent`

\- `distribution`

\- `recruitment`

\- `confusion\\\_masking`



Output:

\- primary class

\- secondary class

\- class confidence note



\---



\## 5.6 Behavior Direction Estimator

Purpose:

Estimate what the narrative wants the receiver to do.



Possible outputs:

\- `buy`

\- `sell`

\- `hold`

\- `wait`

\- `calm\\\_down`

\- `comply`

\- `engage`

\- `avoid`

\- `defer\\\_judgment`

\- `signal\\\_alignment`



Output:

\- target behavior

\- direction strength

\- target audience note



\---



\## 5.7 Timing Detector

Purpose:

Measure whether timing increases the probability of purposeful intent.



Looks for:

\- appearance after a move

\- appearance during stress

\- appearance during fragility

\- appearance near a catalyst

\- appearance during uncertainty spikes



Output:

\- timing score

\- timing relation type

\- why-now summary



\---



\## 5.8 Beneficiary Mapper

Purpose:

Estimate who gains if the target behavior occurs.



Possible beneficiary types:

\- issuer / narrator

\- institution

\- holder / distributor

\- recruiter

\- stabilizer

\- audience subgroup

\- self-image preserving actor

\- diffuse / emergent beneficiary set



Output:

\- likely beneficiaries

\- confidence level

\- direct vs diffuse beneficiary note



\---



\## 5.9 Narrative Intent Detector

Purpose:

Produce the final synthetic reading.



Combines:

\- hook

\- distortion

\- trap

\- direction

\- timing

\- beneficiary mapping



Output:

\- narrative intent score

\- primary intent class

\- supporting rationale

\- risks / ambiguity flags



\---



\## 6. Canonical Scores



\## 6.1 Hook Score

Measures:

Strength of credible / attractive / authoritative anchor.



High when:

\- frame is clean

\- source is trusted

\- aesthetics or legitimacy are strong



Low when:

\- no anchor

\- weak credibility

\- no attention entry point



\---



\## 6.2 Distortion Score

Measures:

Degree of contradiction, mismatch, simplification, or inconsistency.



High when:

\- strong frame-content mismatch

\- sharp contradiction

\- purposeful omission or compression



Low when:

\- clean continuity between frame and content



\---



\## 6.3 Trap Score

Measures:

How much the narrative forces unresolved interpretation.



High when:

\- content demands classification

\- closure is withheld

\- ambiguity is interpretable, not random



Low when:

\- narrative is cleanly resolved

\- ambiguity is absent or incoherent



\---



\## 6.4 Identity Instability Score

Measures:

How many plausible, competing readings of the same subject exist.



High when:

\- persona remains unresolved

\- multiple incompatible labels remain live



Low when:

\- identity is stable and obvious



\---



\## 6.5 Intent Score

Measures:

How strongly distortion appears linked to a directional behavioral aim.



High when:

\- distortion is purposeful

\- target behavior is inferable

\- timing supports non-random intent



Low when:

\- distortion seems random

\- no directional effect is inferable



\---



\## 6.6 Narrative Intent Score

Measures:

Overall structural potency of a narrative as a behavior-coordination object.



Combines:

\- hook

\- distortion

\- trap

\- timing

\- beneficiary clarity

\- directionality



\---



\## 6.7 Signal Conflict Score

Measures:

Tension between dominant narrative strength and contradiction strength.



Useful especially for:

\- markets

\- institutional messaging

\- crowded consensus environments



\---



\## 6.8 Meme Signal Score

Measures:

Potency of a content artifact as a compressed attention engine.



Combines:

\- hook

\- distortion

\- ambiguity



\---



\## 7. Narrative Typology



\### Pure Signal

Mostly informative, low distortion, low manipulation.



\### Noise

Low coherence, low direction, low useful structure.



\### Engineered Narrative

Purposeful framing with directional or control effects.



\### Stabilizing

Reduces panic, preserves order, buys time.



\### Protective

Shields fragile targets from complexity or overload.



\### Exploitative

Extracts advantage from others’ belief or action.



\### Motivational

Pushes compliance, effort, or focus.



\### Emergent

Not centrally designed; arises from distributed behavior.



\### Distribution

Late-stage narrative that may help exit, transfer, or offload.



\### Recruitment

Narrative designed to pull new participants into a belief or trade.



\### Confusion / Masking

Narrative that obscures true state or delays recognition.



\---



\## 8. Domain Adapters



\## 8.1 Markets

Keep:

\- hook / distortion / timing / beneficiary logic



Add:

\- price context

\- consensus density

\- execution friction

\- regime sensitivity



Do not assume:

\- meme logic maps directly without market context



\---



\## 8.2 Social Media / Memes

Keep:

\- hook / distortion / trap / identity instability



Add:

\- visual frame

\- engagement loops

\- comment ambiguity

\- status signaling



Do not assume:

\- engagement equals durable control



\---



\## 8.3 Football / Sports Messaging

Keep:

\- distortion / stabilization / beneficiary logic



Add:

\- club incentives

\- manager protection

\- supporter mood

\- media cycle timing



Do not assume:

\- surface calm equals underlying calm



\---



\## 8.4 Interpersonal Communication

Keep:

\- simplification / distortion / timing / beneficiary logic



Add:

\- self-image protection

\- conflict avoidance

\- emotional regulation

\- local context



Do not assume:

\- all distortion is strategic or exploitative



\---



\## 9. Canonical Output Objects



This system should eventually emit:



\- `HookReport`

\- `DistortionReport`

\- `TrapReport`

\- `NarrativeIntentReport`



Optional later:

\- `BeneficiaryMap`

\- `BehaviorDirectionEstimate`

\- `CrossDomainAdapterReport`



\---



\## 10. Integration Boundary with Repo



Near-term:

\- docs only

\- schemas only

\- examples only



Mid-term:

\- separate analysis module or package

\- standalone evaluator on sample artifacts



Long-term:

\- optional orchestrated narrative enrichment

\- future feature generation for research or decision-support layers



Hard constraint:

This layer must remain outside current tagging-v1 implementation.



\---



\## 11. Main Failure Modes



\- scope creep into tagging-v1

\- treating this as a hidden rewrite of readiness scoring

\- assuming every narrative is designed

\- equating distortion with malice

\- collapsing all domains into one undifferentiated model

\- producing scores without interpretable linked reports

\- overfitting ambiguity as always good

\- forcing beneficiary certainty where only probabilistic inference is justified



\---



\## 12. Best Next Non-Coding Milestone



Freeze:

\- input bundle

\- output schemas

\- score definitions

\- narrative typology

\- domain adapter contract



This is the correct next milestone before any detector code is built.

