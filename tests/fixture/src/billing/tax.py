"""Tax rules."""
from decimal import Decimal
from src.billing.repo import OrderRepo


class TaxCalculator:
    """Calcula impostos de pedidos."""

    def __init__(self, repo: OrderRepo):
        self.repo = repo

    def calcular_imposto(self, order_id: int) -> Decimal:
        """Returns the tax amount for an order."""
        order = self.repo.get(order_id)
        return order.total * self._rate(order.state)

    def _rate(self, state):
        # aliquota por estado
        return Decimal("0.17")


def desconto(order):
    """Aplica desconto."""
    return TaxCalculator(None).calcular_imposto(order) * 0
