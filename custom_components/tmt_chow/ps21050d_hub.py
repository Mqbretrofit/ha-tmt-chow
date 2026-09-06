"""PS21050D live-identity alias support derived from the vendor Android app."""

from __future__ import annotations

from .controller_types import controller_capabilities, controller_family
from .hub import TmtChowHub as BaseTmtChowHub
from .model_parameter_schemas import parameter_schema_for

_LIVE_MODEL = "PS21050D"
_APK_MODEL = "PS21050"


class TmtChowHub(BaseTmtChowHub):
    """Use the official PS21050 app profile for live PS21050D hardware.

    TMT Chow 3.1.4 contains a PS21050 product implementation but no separate
    PS21050D implementation.  The account API identifies this controller as
    PS21050, while live DEV INFO reports PS21050D.  Preserve the concrete live
    identity but use the app's PS21050 family, capabilities and 20-parameter
    RP,1/WP,1 profile for that exact alias pair.
    """

    def _set_controller_type(self, controller_type: str | None) -> None:
        normalized = (controller_type or "").strip().upper()
        if (
            normalized == _LIVE_MODEL
            and self.configured_controller_type == _APK_MODEL
        ):
            self.controller_type = _LIVE_MODEL
            self.controller_family = controller_family(_APK_MODEL)
            self.controller_capabilities = controller_capabilities(_APK_MODEL)
            self.parameter_model_type = _APK_MODEL
            self.parameter_model_source = "apk_ps21050_alias"
            self.model_parameter_schema = parameter_schema_for(_APK_MODEL)
            return
        super()._set_controller_type(controller_type)

    @property
    def parameter_write_schema_verified(self) -> bool:
        """Allow writes only for the exact app-proven PS21050D/PS21050 alias."""
        if (
            self.controller_type == _LIVE_MODEL
            and self.configured_controller_type == _APK_MODEL
            and self.parameter_model_type == _APK_MODEL
        ):
            return self.parameter_schema_verified
        return super().parameter_write_schema_verified
