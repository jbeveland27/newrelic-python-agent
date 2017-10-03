import asyncio
from aiohttp import web


@asyncio.coroutine
def index(request):
    yield
    return web.Response(text='Hello Aiohttp!')


@asyncio.coroutine
def error(request):
    raise ValueError("I'm bad at programming...")


class HelloWorldView(web.View):

    @asyncio.coroutine
    def _respond(self):
        yield
        return web.Response(text='Hello Aiohttp!')

    get = _respond
    post = _respond
    put = _respond
    patch = _respond
    delete = _respond


class KnownException(Exception):
    pass


class KnownErrorView(web.View):

    @asyncio.coroutine
    def _respond(self):
        try:
            yield
        except KnownException:
            pass
        finally:
            return web.Response(text='Hello Aiohttp!')

    get = _respond
    post = _respond
    put = _respond
    patch = _respond
    delete = _respond


@asyncio.coroutine
def load_close_middleware(app, handler):

    @asyncio.coroutine
    def coro_closer(request):
        # start handler call
        coro = handler(request)
        if hasattr(coro, '__iter__'):
            coro = iter(coro)
        try:
            yield
            next(coro)
            coro.close()
            return web.Response(text='Hello Aiohttp!')
        except StopIteration as e:
            return e.value

    return coro_closer


def make_app(middlewares=None):
    app = web.Application(middlewares=middlewares)
    app.router.add_route('*', '/coro', index)
    app.router.add_route('*', '/class', HelloWorldView)
    app.router.add_route('*', '/error', error)
    app.router.add_route('*', '/known_error', KnownErrorView)

    return app
