# Provider Roadmap

## Immediate direction

CelloS is pivoting away from Trello-specific integration work and toward open-source PM tools.

Priority shortlist:
1. **WeKan** — closest open-source Trello-style board
2. **Plane** — modern issue/project platform
3. **OpenProject** — established organization-grade PM platform

## Strategy

- keep the core integration surface generic
- implement each PM tool as an isolated provider under `cellos/integrations/<provider>/`
- start with the simplest provider first
- avoid hard-coding any provider-specific domain rules into core

## Recommended order

### Phase 1: WeKan
Why first:
- simplest board/list/card model
- likely lowest migration friction from earlier Trello thinking
- good first validation of the generic provider interface

### Phase 2: Plane
Why second:
- richer issue/project model
- good test of whether CelloS should stay task-centric or evolve toward a more issue-oriented connector model

### Phase 3: OpenProject
Why third:
- heavier product
- likely more workflow/configuration surface
- better to tackle after the provider interface is proven
