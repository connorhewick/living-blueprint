from api.queue import publish
from api.repository import OrderRepository


class OrderService:
    """The only writer of the orders table."""

    def __init__(self):
        self.repository = OrderRepository()

    def place(self, cart_id: str):
        order = self.repository.insert(cart_id, status="placed")
        publish("order.placed", order)
        return order

    def find(self, order_id: str):
        return self.repository.get(order_id)
