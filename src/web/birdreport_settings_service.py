from src.records.secrets import clear_birdreport_token, load_birdreport_token, save_birdreport_token


class BirdReportSettingsService:
    def __init__(self, base_dir, client_factory):
        self.base_dir = base_dir
        self.client_factory = client_factory

    def status(self):
        return {"configured": bool(load_birdreport_token(self.base_dir)), "connected": None, "username": None}

    def save(self, token, test=True):
        save_birdreport_token(self.base_dir, token)
        return self.test() if test else self.status()

    def test(self):
        result = self.client_factory().test_connection()
        return {"configured": True, "connected": result.connected, "username": result.username}

    def clear(self):
        clear_birdreport_token(self.base_dir)
        return self.status()
