"""Small, coalescing wake-up cursor; snapshots remain the source of truth."""
import asyncio


class StateChanges:
    def __init__(self, instance):
        self.instance, self.revision = instance, 0
        self.changed = asyncio.Event()

    def publish(self):
        self.revision += 1
        previous, self.changed = self.changed, asyncio.Event()
        previous.set()

    async def wait(self, revision, instance, timeout=20):
        if instance == self.instance and revision == self.revision:
            try:
                await asyncio.wait_for(self.changed.wait(), timeout)
            except TimeoutError:
                pass
        return dict(instance=self.instance, revision=self.revision)
