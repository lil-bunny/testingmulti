# from app.services.turvo_service import TurvoService

def get_shipment(shipment_id):
    # turvo_client = TurvoService()
    # shipment_data = turvo_client.get_shipment_details(shipment_id)
    shipment_data=turvo_response['details']
    return {
        "shipment_id": shipment_id,
        "convoy": False,
        "data": shipment_data
    }


def update_shipment(data):
    print(f"[SHIPMENT UPDATE]")


def upload_to_turvo(data):
    """Scaffold: upload artifacts to Turvo (implementation pending)."""
    pass