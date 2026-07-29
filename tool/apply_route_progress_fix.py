from pathlib import Path

serializer = Path("apps/delivery/serializer.py")
text = serializer.read_text(encoding="utf-8")
old = "            shipment.current_stop_index = 1\n"
new = "            shipment.current_stop_index = 0\n"
if old not in text:
    raise RuntimeError("Shipment initial stop index block not found")
serializer.write_text(text.replace(old, new, 1), encoding="utf-8")

tests = Path("apps/delivery/test_contracts.py")
text = tests.read_text(encoding="utf-8")
marker = '''    def test_delete_cancels_without_erasing_record(self):
        self.client.force_authenticate(self.client_user)
        response = self.client.delete(f"/api/delivery/shipments/{self.shipment.id}/")
        self.assertEqual(response.status_code, 204)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.CANCELED)
'''
replacement = marker + '''

    def test_two_stop_route_requires_start_then_complete(self):
        self.client.force_authenticate(self.carrier)
        self.shipment.current_stop_index = 0
        self.shipment.save(update_fields=["current_stop_index"])

        started = self.client.post(f"/api/delivery/shipments/{self.shipment.id}/advance/")
        self.assertEqual(started.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.IN_TRANSIT)
        self.assertEqual(self.shipment.current_stop_index, 1)

        completed = self.client.post(f"/api/delivery/shipments/{self.shipment.id}/advance/")
        self.assertEqual(completed.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.COMPLETED)
        self.assertTrue(self.shipment.rating_applied)
'''
if marker not in text:
    raise RuntimeError("Contract test insertion point not found")
tests.write_text(text.replace(marker, replacement, 1), encoding="utf-8")

print("Route progress fix applied")
