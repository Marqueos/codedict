from fastapi import FastAPI
from src.billing.tax import TaxCalculator
from src.billing.repo import OrderRepo

app = FastAPI()

@app.get("/orders/{order_id}/tax")
def get_tax(order_id: int):
    calc = TaxCalculator(OrderRepo())
    return {"tax": calc.calcular_imposto(order_id)}
