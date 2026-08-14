# Quick Checklist

Before approving any UI work:

## Design System Compliance
- [ ] Component verified in your Figma Design System
- [ ] Component implementation checked in your Component Library
- [ ] Figma Dev Mode specs followed (spacing, tokens, typography)
- [ ] Design tokens used (no hardcoded hex colors or pixel values)
- [ ] Token imports verified in code
- [ ] All variants/states implemented as designed in Figma
- [ ] Spacing measurements match Figma Dev Mode exactly
- [ ] Deviations documented with design approval

## Aesthetic Quality (especially for new designs)
- [ ] Clear conceptual direction (not generic overused fonts and cliched schemes)
- [ ] Distinctive typography (avoid overused fonts)
- [ ] Cohesive color palette with CSS variables
- [ ] Every color has a clear role: neutral surface, brand/action, or semantic information; decorative emphasis does not compete with semantic colors
- [ ] Intentional motion (staggered reveals, hover states)
- [ ] Visual interest through composition (asymmetry, overlap, grid-breaking)
- [ ] Atmosphere through backgrounds (gradients, textures, patterns)
- [ ] Implementation complexity matches vision

## Stateful Visual and Interaction Validation
- [ ] Defined and visually inspected the relevant default, loading, empty, error, selected, and expanded/collapsed states
- [ ] Checked each route transition from a realistic preceding state, including navigation after scrolling and browser back behavior
- [ ] Checked narrow desktop and mobile layouts when the UI has responsive breakpoints
- [ ] Visually checked shared control groups for aligned edges/baselines, compact height, non-wrapping primary actions, and unintended flex/grid stretching
- [ ] Used rendered geometry only to confirm a visible concern or diagnose its cause
- [ ] Tested every action-signalling chip, token, icon, underline, hover treatment, and cursor by mouse and keyboard
- [ ] Listed any state, viewport, or assistive-technology coverage that was not tested

## Frictionless
- [ ] Core task completable efficiently (≤3 interactions)
- [ ] Single clear primary action per view

## Quality Craft
- [ ] Uses design system components (verified in Figma)
- [ ] Design tokens used (no hardcoded values)
- [ ] Distinctive aesthetic (not generic overused fonts/cliched schemes)
- [ ] Accessible (Grade C minimum, Grade B ideal)
- [ ] Keyboard navigation complete
- [ ] Tested in light/dark/high contrast modes

## Trustworthy
- [ ] AI-generated content has disclaimer
- [ ] Error messages are actionable
