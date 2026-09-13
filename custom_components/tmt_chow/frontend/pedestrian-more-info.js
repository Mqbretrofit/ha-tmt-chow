const FLAG_ATTRIBUTE = "tmt_chow_pedestrian_supported";
const UUID_ATTRIBUTE = "tmt_chow_pedestrian_uuid";
const BUTTON_MARKER = "tmt-chow-pedestrian";
const PATCH_MARKER = "__tmtChowPedestrianPatched";

const getHass = () => document.querySelector("home-assistant")?.hass;

const pedestrianLabel = () => {
  const hass = getHass();
  return (
    hass?.localize?.("component.tmt_chow.entity.button.pedestrian_open.name") ||
    "Pedestrian opening"
  );
};

const showError = (element, error) => {
  const message = error?.message || "TMT Chow pedestrian opening failed";
  element.dispatchEvent(
    new CustomEvent("hass-notification", {
      bubbles: true,
      composed: true,
      detail: { message },
    })
  );
};

const syncPedestrianButton = (control) => {
  const root = control.renderRoot || control.shadowRoot;
  if (!root) return;

  const stateObj = control.stateObj;
  const supported = stateObj?.attributes?.[FLAG_ATTRIBUTE] === true;
  const group = root.querySelector("ha-control-button-group");
  let button = root.querySelector(`[data-button="${BUTTON_MARKER}"]`);

  if (!supported || !group) {
    button?.remove();
    if (group) {
      group.style.removeProperty("--control-button-group-thickness");
      group.style.removeProperty("height");
      group.style.removeProperty("max-height");
      group.style.removeProperty("min-height");
    }
    return;
  }

  if (!button) {
    button = document.createElement("ha-control-button");
    button.dataset.button = BUTTON_MARKER;

    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", "mdi:walk");
    button.append(icon);

    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const hass = getHass();
      const uuid = control.stateObj?.attributes?.[UUID_ATTRIBUTE];
      if (!hass || !uuid) return;

      button.disabled = true;
      try {
        await hass.callService("tmt_chow", "pedestrian_open", { uuid });
      } catch (error) {
        showError(control, error);
      } finally {
        button.disabled = control.stateObj?.state === "unavailable";
      }
    });

    const children = Array.from(group.children);
    const stopButton = children.find((child) => child.dataset?.button === "stop");
    if (stopButton) {
      group.insertBefore(button, stopButton);
    } else {
      group.append(button);
    }
  }

  const label = pedestrianLabel();
  button.label = label;
  button.setAttribute("aria-label", label);
  button.disabled = stateObj?.state === "unavailable";

  // Four native-style round controls fit comfortably in the standard dialog
  // without changing Home Assistant's cover semantics or pretending PED is tilt.
  group.style.setProperty("--control-button-group-thickness", "74px");
  group.style.setProperty("height", "min(52vh, 356px)");
  group.style.setProperty("max-height", "356px");
  group.style.setProperty("min-height", "326px");
};

const installPatch = async () => {
  await customElements.whenDefined("ha-state-control-cover-buttons");
  const Control = customElements.get("ha-state-control-cover-buttons");
  if (!Control || Control.prototype[PATCH_MARKER]) return;

  const originalUpdated = Control.prototype.updated;
  Control.prototype.updated = function (changedProperties) {
    if (originalUpdated) {
      originalUpdated.call(this, changedProperties);
    }
    queueMicrotask(() => syncPedestrianButton(this));
  };

  Control.prototype[PATCH_MARKER] = true;
};

installPatch();
