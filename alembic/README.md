# Migrations (Alembic)

```bash
# Tạo migration mới từ thay đổi models.py
alembic revision --autogenerate -m "mô tả thay đổi"

# Áp dụng lên DB (DATABASE_URL lấy từ env qua app.config)
alembic upgrade head

# Rollback 1 bước
alembic downgrade -1
```

Migration đầu (`0001_initial`) tạo toàn bộ schema M0:
tenants, repositories, users, requests, request_events, approvals + các enum.
