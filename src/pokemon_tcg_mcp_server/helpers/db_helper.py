from fastmcp import Context


def get_db(ctx: Context):
    assert ctx.request_context is not None
    client = ctx.request_context.lifespan_context.client
    db = client["pokemon_tcg"]
    return db
