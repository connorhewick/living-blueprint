class OrderRepository:
    def insert(self, cart_id: str, status: str):
        return {"id": cart_id, "status": status}

    def get(self, order_id: str):
        return {"id": order_id}
