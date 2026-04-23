from pathlib import Path

class TribeV2Adapter:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def healthcheck(self) -> dict:
        return {
            "adapter": "tribev2",
            "enabled": self.enabled,
            "mode": "research_only",
            "status": "not_wired"
        }

    def describe_contract(self) -> dict:
        return {
            "inputs": ["video_path", "audio_path", "text_path"],
            "outputs": ["preds", "segments"],
            "notes": [
                "External research model",
                "Keep outside live trading path",
                "Use only as isolated experiment until formally validated"
            ],
        }