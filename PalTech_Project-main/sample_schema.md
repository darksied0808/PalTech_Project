# Customer Orders Database

## Schema

### dbo.Customers

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| CustomerId | INT | NO | Primary key |
| Email | NVARCHAR(255) | NO | Unique customer email |
| Status | VARCHAR(20) | NO | active, inactive, suspended |
| CreatedAt | DATETIME2 | NO | Registration timestamp |
| CountryCode | CHAR(2) | YES | ISO country code |

### dbo.Orders

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| OrderId | BIGINT | NO | Primary key |
| CustomerId | INT | NO | FK to Customers |
| OrderDate | DATE | NO | Order placement date |
| ShippedDate | DATE | YES | Shipment date |
| OrderStatus | VARCHAR(30) | NO | pending, paid, shipped, cancelled, refunded |
| TotalAmount | DECIMAL(18,2) | NO | Order total in USD |
| DiscountAmount | DECIMAL(18,2) | YES | Applied discount |

### dbo.OrderItems

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| OrderItemId | BIGINT | NO | Primary key |
| OrderId | BIGINT | NO | FK to Orders |
| ProductId | INT | NO | FK to Products |
| Quantity | INT | NO | Must be > 0 |
| UnitPrice | DECIMAL(18,2) | NO | Price at time of order |

## Business Rules

- Every order must belong to an existing active customer at the time of order placement.
- `ShippedDate` must be NULL when `OrderStatus` is pending or paid, and must be populated when status is shipped.
- `TotalAmount` must equal the sum of (Quantity * UnitPrice) minus `DiscountAmount` for all line items.
- Cancelled orders must have `TotalAmount` >= 0 but line items may remain for audit.
- Email addresses must be unique across all customers.
- Orders cannot be placed with a future `OrderDate`.
- Refunded orders must have been previously shipped.

## Edge Cases

- Orders with zero discount vs NULL discount should be treated differently in reporting.
- Customer status may change after order creation; historical orders remain valid.
- Duplicate emails differing only by case (e.g. User@mail.com vs user@mail.com).
- Negative `DiscountAmount` values (data entry errors).
- Orders with `ShippedDate` before `OrderDate`.
- Orphan `OrderItems` referencing deleted orders.
- `Quantity` of 0 or negative due to import errors.
- Multiple orders on the same day for the same customer (valid but worth profiling).
