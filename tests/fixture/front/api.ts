import { http } from './http';

/** Fetches an order from the backend. */
export const fetchOrder = async (id: number): Promise<Order> => {
  return http.get(`/api/orders/${id}`);
};

export class OrderClient {
  constructor(private base: string) {}
  async load(id: number) { return fetchOrder(id); }
}

router.get('/health', (req, res) => res.send('ok'));
