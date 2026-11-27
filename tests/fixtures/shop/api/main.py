from fastapi import FastAPI

from api.orders import OrderService

app = FastAPI()
orders = OrderService()


@app.post("/orders")
def create_order(payload: dict):
    return orders.place(payload["cartId"])


@app.get("/orders/{order_id}")
def read_order(order_id: str):
    return orders.find(order_id)
