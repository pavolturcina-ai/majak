from majak.api.routers import (
    days,
    inputs,
    items,
    people,
    review,
    rollup,
    scheduler,
    sources,
)

routers = [
    days.router,
    items.router,
    people.router,
    sources.router,
    inputs.router,
    review.router,
    rollup.router,
    scheduler.router,
]

__all__ = ["routers"]
