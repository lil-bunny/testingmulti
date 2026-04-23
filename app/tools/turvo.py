def get_shipment(shipment_id):
    return {
        "shipment_id": shipment_id,
        "convoy": False
    }


def update_shipment(data):
    print(f"[SHIPMENT UPDATE] {data}")