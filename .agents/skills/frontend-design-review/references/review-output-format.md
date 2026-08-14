# Review Output Format

```
## Frontend Design Review: [Component/Feature Name]

### Context
- **Purpose**: What problem does this solve? Who uses it?
- **Aesthetic Direction**: [If new design: describe the bold conceptual direction]
- **User Task**: What is the user trying to accomplish?

### Summary
[Pass/Needs Work/Blocked] - [One-line assessment]

### Verification Coverage

| State or flow | Visual check | Interaction check | Geometry check | Result |
|---|---|---|---|---|
| Default desktop | Yes/No | N/A | Yes/No | Pass/Issue |
| Relevant alternate state (for example collapsed, loading, selected, empty, or error) | Yes/No | Yes/No | Yes/No | Pass/Issue |
| Navigation from a scrolled position | Yes/No | Yes/No | N/A | Pass/Issue |
| Narrow desktop / mobile | Yes/No | Yes/No | Yes/No | Pass/Issue |

State the exact untested states or viewports. Do not describe the UI as fully verified when this table has gaps.

### Design System Compliance (if applicable)
- [ ] Component exists in [Your Figma Design System]
- [ ] Component usage verified in [Your Component Library]
- [ ] Implementation matches Figma specs (spacing, colors, typography)
- [ ] Uses design tokens (not hardcoded values) - verified in code
- [ ] All variants match design system options
- [ ] Spacing verified against Figma Dev Mode
- [ ] Documented exception if deviating from design system

### Aesthetic Quality (especially for new designs)
- [ ] Clear conceptual direction (not generic AI aesthetic)
- [ ] Distinctive typography choices
- [ ] Cohesive color palette with CSS variables
- [ ] Intentional motion and micro-interactions
- [ ] Spatial composition creates visual interest
- [ ] Backgrounds and visual details add atmosphere

### Pillar Assessment

| Pillar | Status | Notes |
|--------|--------|-------|
| Frictionless | 🟢/🟠/⚫ | Task completion efficient, primary action clear |
| Quality Craft | 🟢/🟠/⚫ | Design system compliant, aesthetic distinctive, accessible |
| Trustworthy | 🟢/🟠/⚫ | AI disclaimers present, errors actionable |

**Legend:** 🟢 Pass | 🟠 Needs attention | ⚫ Blocking issue

### Design Critique
**Verdict:** [Pass / Needs work / Reach out to design for more support]

**Rationale:** [Brief explanation based on pillar assessment, design system compliance, and aesthetic direction]

**Criteria:**
- **Pass**: All pillars 🟢 or minor 🟠 that don't block user tasks, design system compliant, clear aesthetic direction
- **Needs work**: Multiple 🟠 or any critical workflow issues, design system deviations, or generic aesthetic choices
- **Reach out to design for more support**: Any ⚫ blocking issues, fundamental pattern problems, major design system violations, or need for aesthetic direction

### Issues

**Blocking (must fix before merge):**
1. [Pillar/Design System/Aesthetic] Issue description + recommendation with link

**Major (should fix):**
1. [Pillar/Design System/Aesthetic] Issue description + pattern suggestion with reference

**Minor (consider for refinement):**
1. [Pillar/Design System/Aesthetic] Issue description + optional improvement

### Recommendations
- [Design system component to use with link]
- [Specific code change with design token reference]
- [Typography recommendation for better aesthetic direction]
- [Motion/animation suggestion]
- [Link to design system in Figma]

### Implementation Recheck (when code changed)
- Re-run the relevant rows in Verification Coverage after the change.
- Recheck sibling alignment after adding helper text, badges, or status rows.
- Confirm that visual affordances and their actions still agree.
```
