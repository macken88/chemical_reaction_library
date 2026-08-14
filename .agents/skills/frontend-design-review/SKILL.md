---
name: frontend-design-review
description: >
  Review and create distinctive, production-grade frontend interfaces with high design quality and design system compliance.
  Evaluates using three pillars: frictionless insight-to-action, quality craft, and trustworthy building.
  USE FOR: PR reviews, design reviews, accessibility audits, design system compliance checks, creative frontend design,
  UI code review, component reviews, responsive design checks, theme testing, and creating memorable UI.
  Verify stateful layouts, navigation behavior, interaction affordances, and rendered control geometry instead of relying on static screenshots alone.
  DO NOT USE FOR: Backend API reviews, database schema reviews, infrastructure or DevOps work, pure business logic
  without UI, or non-frontend code.
acknowledgments: |
  Design review principles and quality pillar framework created by @Quirinevwm (https://github.com/Quirinevwm).
  Creative frontend guidance inspired by Anthropic's frontend-design skill
  (https://github.com/anthropics/skills/tree/main/skills/frontend-design). Licensed under respective terms.
---

# Frontend Design Review

Review UI implementations against design quality standards and your design system **OR** create distinctive, production-grade frontend interfaces from scratch.

## Two Modes

### Mode 1: Design Review
Evaluate existing UI for design system compliance, three quality pillars (Frictionless, Quality Craft, Trustworthy), accessibility, and code quality.

### Mode 2: Creative Frontend Design
Create distinctive interfaces that avoid generic "AI slop" aesthetics, have clear conceptual direction, and execute with precision.

---

## Creative Frontend Design

Before coding, commit to an aesthetic direction:
- **Purpose**: What problem does this solve? Who uses it?
- **Tone**: minimal, maximalist, retro-futuristic, organic, luxury, playful, editorial, brutalist, art deco, soft/pastel, industrial, etc.
- **Constraints**: Framework, performance, accessibility requirements.
- **Differentiation**: What makes this distinctive and context-appropriate?

### Aesthetics Guidelines

- **Typography**: Distinctive fonts that elevate aesthetics. Pair a display font with a refined body font. Avoid Inter, Roboto, Arial, Space Grotesk.
- **Color & Theme**: Cohesive palette with CSS variables. Dominant colors + sharp accents > timid, evenly-distributed palettes.
- **Motion**: CSS-only preferred. One well-orchestrated page load with staggered reveals > scattered micro-interactions.
- **Spatial Composition**: Asymmetry, overlap, diagonal flow, grid-breaking elements, generous negative space OR controlled density.
- **Backgrounds**: Gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows, grain overlays.

**AVOID**: Overused fonts, cliched color schemes, predictable layouts, cookie-cutter design without context-specific character.

Match implementation complexity to vision. Maximalist = elaborate code. Minimalist = restraint and precision.

---

## Design Review

### Design System Workflow

**Before implementing:**
1. Review component in your Storybook / component library for API and usage
2. Use Figma Dev Mode to get exact specs (spacing, tokens, properties)
3. Implement using design system components + design tokens

**During review:**
1. Compare implementation to Figma design
2. Verify design tokens are used (not hardcoded values)
3. Check all variants/states are implemented correctly
4. Flag deviations (needs design approval)

**If component doesn't exist:**
1. Check if existing component can be adapted
2. Reach out to design for new component creation
3. Document exception and rationale in code

### Review Process

1. Identify user task
2. Check design system for matching patterns
3. Evaluate aesthetic direction
4. Identify scope (component, feature, or flow)
5. Define the state and flow matrix before judging the UI
6. Inspect rendered UI, then execute the relevant interactions
7. Measure rendered geometry only where it confirms or explains a visual finding
8. Evaluate each pillar
9. Score and prioritize issues (blocking/major/minor)
10. Provide recommendations with design system examples

### Stateful Visual and Interaction Validation

Treat a static screenshot as only one state, never as proof that a UI flow works.

1. List the relevant states before reviewing or implementing: default, loading, empty, error, selected, expanded/collapsed, and any route transition. Add narrow desktop and mobile states when the layout changes at those widths.
2. Review the rendered page visually first. Flag visible imbalance, unexpected wrapping, inconsistent control height, misaligned edges, oversized controls, or excess color emphasis even before measuring it.
3. For controls that belong to one task, verify a shared visual rhythm: aligned baselines, compact target sizes, no accidental stretching, and no wrapped primary-action labels.
4. Use computed styles or bounding rectangles to confirm the cause and magnitude of a suspected layout issue. Measurements support visual judgment; they do not replace it.
5. Execute each critical flow, including navigation from a scrolled position. Verify the intended scroll policy, entry point, exit point, and browser back behavior.
6. Test every chip, token, icon, underline, hover treatment, or cursor that suggests an action. A control that looks actionable must be a semantic button or link and must complete its implied action by mouse and keyboard.
7. Audit colors by role, not by the existence of variables. Distinguish neutral surfaces, brand/action color, and semantic data-layer colors; do not use every semantic color as decorative emphasis.

After an implementation, rerun the affected state matrix. In particular, recheck parent alignment after adding helper text, badges, or status rows because flex and grid containers can stretch sibling controls. Report only the states and interactions actually verified; list untested coverage explicitly.

### Core Principles

- **Task completion**: Minimum clicks. Every screen answers "What can I do?" and "What happens next?"
- **Action hierarchy**: 1-2 primary actions per view. Progressive disclosure for secondary.
- **Onboarding**: Explain features on introduction. Smart defaults over configuration.
- **Navigation**: Clear entry/exit points. Back/cancel always available. Breadcrumbs for deep flows.

---

## Quality Pillars

### 1. Frictionless Insight to Action

**Evaluate:** Task completable in ≤3 interactions? Primary action obvious and singular?

**Red flags:** Excessive clicks, multiple competing primary buttons, buried actions, dead ends.

### 2. Quality is Craft

**Evaluate:**
- Design system compliance: matches Figma specs, uses design tokens
- Aesthetic direction: distinctive typography, cohesive colors, intentional motion
- Accessibility: Grade C minimum (WCAG 2.1 A), Grade B ideal (WCAG 2.1 AA)

**Red flags:** Generic AI aesthetics, hardcoded values, implementation doesn't match Figma, broken reflow, missing focus indicators.

### 3. Trustworthy Building

**Evaluate:**
- AI transparency: disclaimer on AI-generated content
- Error transparency: actionable error messages

**Red flags:** Missing AI disclaimers, opaque errors without guidance.

---

## Review Output Format

For a design review, read and use [references/review-output-format.md](references/review-output-format.md). Complete its Verification Coverage section from executed checks rather than assumptions.

## Review Type Modifiers

See [references/review-type-modifiers.md](references/review-type-modifiers.md) for context-specific review focus areas (PR, Creative, Design, Accessibility).

## Quick Checklist

Before approving or handing off UI work, read and complete [references/quick-checklist.md](references/quick-checklist.md), including Stateful Visual and Interaction Validation.

## Pattern Examples

See [references/pattern-examples.md](references/pattern-examples.md) for good/bad examples of creative frontend and design system review work.

---

## Acknowledgments

Creative frontend principles inspired by [Anthropic's frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design). Design review principles and quality pillar framework created by [@Quirinevwm](https://github.com/Quirinevwm) for systematic UI evaluation.
