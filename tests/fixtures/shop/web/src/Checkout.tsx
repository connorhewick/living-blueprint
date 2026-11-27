export function Checkout({ cartId }: { cartId: string }) {
  async function placeOrder() {
    await fetch("/orders", { method: "POST", body: JSON.stringify({ cartId }) });
  }
  return <button onClick={placeOrder}>Place order</button>;
}
