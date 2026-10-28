namespace Web.Services
{
    public interface IOrderService { Order FindOrder(int id); void Save(Order o); }

    /// <summary>Regras de negócio de pedidos.</summary>
    public class OrderService : IOrderService
    {
        public Order FindOrder(int id) => _db.QuerySingle<Order>("SELECT * FROM dbo.Orders WHERE Id = @id", new { id });
        public void Save(Order o) { _db.Execute("EXEC dbo.usp_SaveOrder @Id", o); }
        public decimal Total { get; set; }
    }
    public record Order(int Id, decimal Total);
}
