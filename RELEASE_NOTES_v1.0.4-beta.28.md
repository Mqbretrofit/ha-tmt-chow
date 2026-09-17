# TMT Chow v1.0.4-beta.28

## Fix the PS25007A user interface regression

- The PS25007A pedestrian button now uses the exact runtime alias strategy for both entity creation and availability, so the requested guarded `PED OPEN` test path is enabled when the live controller, authenticated source tag, and closed/stopped state requirements are met.
- The verified PS25007A 17-slot parameter profile now reuses the established stable parameter and option keys, restoring Home Assistant translations such as Hungarian labels and values.
- The beta.27 protocol mapping, full-frame parameter write verification, and one-shot/no-retry pedestrian command behavior remain unchanged.
- PS25142 and all unrelated controller profiles are unchanged.
