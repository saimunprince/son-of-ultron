# The 14 plan items still MISSING: what each would mean for SYRAX

Written 2026-10-31, after directions 18, 87 and 100 were built. Each item below gets:

- what it would concretely be on one owner's PC;
- how it would be measured;
- a recommendation.

The rule from the plan holds: nothing counts as done without a check that proves it.

## Build: concrete and measurable from the journal

- **298 Human-impact evaluation.** This measures what SYRAX costs and gives the owner, not only whether its tasks
  pass. The cost side:
  - questions it asked;
  - permission prompts;
  - refusals the owner ran into;
  - undos, since an undo is a wrong action;
  - disputes ("that's not what I asked");
  - windows it opened on the owner's screen.

  The other side is requests finished without any of those. It becomes a weekly number with a trend, like the other
  `rise` metrics, and a rise in cost is journaled as drift. Check: a test journal with known events gives known
  numbers.
- **196 Value-conflict analysis.** The owner's rules live in memory, as facts of type `rule`. When a request
  contradicts one, SYRAX says so before it acts. Example: the rule "never push on Fridays" and the request "push
  now", on a Friday. Check: a quality case with a stored rule and a conflicting request.

## Re-classify: the code already does part of it

- **248 Cross-domain discovery → PARTIAL.** A lesson learned on one subject already reaches another subject with the
  same check (`ee435b9`, transfer lessons in the autonomy's past experience). What is missing is a discovery that
  links two unrelated domains.

## Owner's decision

- **157 Personality adaptation.** The persona is the owner's own choice. Adapting it automatically would change who
  SYRAX is without being asked. Recommendation: no, unless the owner wants it.
- **204 Visual tracking and 206 Sensor fusion.** These would be things like webcam hand gestures (Ultron has them) or
  combining camera, microphone and screen. They need OpenCV, a new dependency, and the camera on all the time.
  Recommendation: only if the owner wants gesture control.

## Decided against, with the reason

- **138 Distributed task queues.** SYRAX runs on one PC with one queue by design. A distributed queue adds failure
  modes and gives nothing here.
- **161 Theory of mind and 163 Perspective taking.** A "model of what the human believes" would be a guess written by
  the same brain it is meant to check, and nothing could prove it right. The measurable part already exists:
  - disputes are detected;
  - exact instructions are held exactly;
  - the language follows the human's message.
- **191 Moral-reasoning models, 195 Fairness analysis and 198 Ethical uncertainty.** On a personal agent the concrete
  form of these is the permission system, which already exists and is tested:
  - destructive or external actions are asked or refused;
  - reversibility is stated in every question;
  - own work never acts on the screen;
  - the hard rules are in the persona.

  A separate "moral model" would be prompt text with no check behind it.
- **243 Simulation-based discovery.** The useful form already exists. Experiments run interleaved arms with a
  permutation test, and code changes run in a worktree through the gate before they land. A simulator of the
  owner's world would be a guess.
- **77 Audience adaptation.** SYRAX has one audience, the owner, and the owner's stated preferences already reach
  every prompt through memory.

## What this does to the plan status

If 298 and 196 are built and 248 is re-classified:

- MISSING goes from 14 to 3: 157, 204 and 206, which wait for the owner.
- 8 more items move to "decided against", each with its reason above.
