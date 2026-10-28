class OrderRepo:
    def get(self, order_id):
        return self.db.query("SELECT * FROM dbo.Orders o JOIN dbo.Customers c ON c.Id = o.CustomerId WHERE o.Id = ?", order_id)

    def save(self, order):
        self.db.execute("UPDATE dbo.Orders SET Total = ? WHERE Id = ?", order.total, order.id)
