using Web.Services;

namespace Web.Controllers;

/// <summary>Endpoints de pedidos.</summary>
[ApiController]
[Route("api/[controller]")]
public class OrdersController : ControllerBase
{
    private readonly IOrderService _orderService;
    public OrdersController(IOrderService orderService) { _orderService = orderService; }

    /// <summary>Busca um pedido pelo id.</summary>
    [HttpGet("{id}")]
    public IActionResult Get(int id) => Ok(_orderService.FindOrder(id));

    [HttpPost]
    public IActionResult Create(OrderDto dto) { var o = new Order(dto); _orderService.Save(o); return Ok(); }
}
