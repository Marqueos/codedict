-- Salva o pedido e recalcula o total
CREATE OR ALTER PROCEDURE dbo.usp_SaveOrder @Id INT AS
BEGIN
  UPDATE dbo.Orders SET UpdatedAt = GETDATE() WHERE Id = @Id;
  EXEC dbo.usp_RecalcTotal @Id;
END
GO
CREATE PROCEDURE [dbo].[usp_RecalcTotal] @Id INT AS
  SELECT SUM(Price) FROM dbo.OrderItems WHERE OrderId = @Id;
GO
CREATE TABLE dbo.Orders (Id INT PRIMARY KEY, Total DECIMAL(10,2));
