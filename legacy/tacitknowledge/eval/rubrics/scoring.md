# Evaluation Scoring Rubric

## Dimensions (0-10 each)

### 1. Technical Correctness (TC)
- **0-3**: Contains errors, incorrect patterns, or anti-patterns
- **4-6**: Correct but conventional, follows standard tutorials
- **7-8**: Technically sound with consideration of edge cases and tradeoffs
- **9-10**: Expert-level correctness, anticipates subtle issues others miss

### 2. Design Quality (DQ)
- **0-3**: Functional but ugly/cluttered, no visual hierarchy
- **4-6**: Clean and organized, follows basic design principles
- **7-8**: Thoughtful hierarchy, rhythm, and balance; feels intentional
- **9-10**: Distinctive, elegant, reveals deep understanding of visual communication

### 3. Depth of Reasoning (DR)
- **0-3**: States "what" without explaining "why"
- **4-6**: Explains reasoning but stays at surface level (e.g., "separation of concerns")
- **7-8**: Reveals underlying principles, tradeoffs, and second-order effects
- **9-10**: Surfaces non-obvious insights, connects to deeper patterns, changes how you think about the problem

### 4. Actionability (AC)
- **0-3**: Abstract advice without concrete steps
- **4-6**: Provides steps but requires significant interpretation
- **7-8**: Clear, implementable guidance with specific code/structure
- **9-10**: Ready to copy-paste or directly implement; anticipates follow-up questions

### 5. Tacit Articulation (TA)
- **0-3**: Only states what's in any tutorial or docs
- **4-6**: Mentions some experiential insight but doesn't develop it
- **7-8**: Articulates "expert intuition" — things experienced practitioners know but rarely explain
- **9-10**: Reveals the "feel" behind decisions — the kind of insight you only get from years of practice, expressed in a way that transfers understanding

## Scoring Rules

1. Score each dimension independently
2. Provide a 1-sentence justification per score
3. Total per prompt = TC + DQ + DR + AC + TA (max 50)
4. Report domain averages (3 prompts per domain)
5. Report overall average
6. Flag any prompt where Enhanced score is LOWER than Baseline (regression)

## Output Format

```json
{
  "prompt_id": "A1",
  "baseline": {
    "TC": { "score": 7, "reason": "..." },
    "DQ": { "score": 5, "reason": "..." },
    "DR": { "score": 6, "reason": "..." },
    "AC": { "score": 7, "reason": "..." },
    "TA": { "score": 4, "reason": "..." },
    "total": 29
  },
  "enhanced": {
    "TC": { "score": 8, "reason": "..." },
    "DQ": { "score": 7, "reason": "..." },
    "DR": { "score": 8, "reason": "..." },
    "AC": { "score": 7, "reason": "..." },
    "TA": { "score": 7, "reason": "..." },
    "total": 37
  },
  "delta": 8,
  "notable": "Enhanced version identified the subsidiary-focal tension in state management that baseline missed entirely"
}
```
