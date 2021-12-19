import ast
import builtins
import functools
import os
import re
import sys
import traceback
from io import StringIO
from itertools import combinations
from random import shuffle
from types import ModuleType
from typing import Union

from asttokens import ASTTokens
from littleutils import strip_required_prefix, strip_required_suffix
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.styles import get_style_by_name


TESTING = False

def stub_module(name):
    assert name not in sys.modules
    sys.modules[name] = ModuleType(name)

stub_module("urllib3")
stub_module("certifi")

lexer = get_lexer_by_name("python3")
monokai = get_style_by_name("monokai")
html_formatter = HtmlFormatter(nowrap=True)

internal_dir = os.path.dirname(os.path.dirname(
    (lambda: 0).__code__.co_filename
))


def no_weird_whitespace(string):
    spaces = set(re.findall(r"\s", string))
    assert spaces <= {" ", "\n"}, spaces


def returns_stdout(func):
    if getattr(func, "returns_stdout", False):
        return func

    @wrap_solution(func)
    def wrapper(*args, **kwargs):
        original = sys.stdout
        sys.stdout = result = StringIO()
        try:
            func(*args, **kwargs)
            return result.getvalue()
        finally:
            sys.stdout = original

    wrapper.returns_stdout = True
    return wrapper


class NoMethodWrapper:
    def __init__(self, func):
        functools.update_wrapper(self, func)
        self.func = func
        self.__name__ = func.__name__

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    @classmethod
    def match(cls, source, target):
        if isinstance(source, cls):
            return cls(target)
        else:
            return target


def wrap_solution(func):
    def decorator(wrapper):
        wrapper = functools.wraps(func)(wrapper)
        wrapper = NoMethodWrapper.match(func, wrapper)
        return wrapper

    return decorator


def make_test_input_callback(stdin_input: Union[str, list]):
    if isinstance(stdin_input, str):
        stdin_input = stdin_input.splitlines()
    assert isinstance(stdin_input, list), repr(stdin_input)
    assert not any("\n" in s for s in stdin_input), repr(stdin_input)

    stdin_input = stdin_input[::-1]

    def input_callback():
        if stdin_input:
            result = stdin_input.pop()
            print(f"<input: {result}>")
            return result
        else:
            raise ValueError("No more test inputs - solution should have finished by now")

    return input_callback


def add_stdin_input_arg(func):
    @wrap_solution(func)
    def wrapper(stdin_input="", **kwargs):
        # TODO also deal with sys.stdin directly,
        #   especially breakpoint()

        input_callback = make_test_input_callback(stdin_input)

        def patched_input(prompt=""):
            print(prompt, end="")
            return input_callback()

        builtins.input = patched_input

        return func(**kwargs)

    return NoMethodWrapper.match(func, wrapper)


def snake(camel_string):
    return re.sub(r'([a-z0-9])([A-Z])',
                  lambda m: (m.group(1).lower() + '_' +
                             m.group(2).lower()),
                  camel_string).lower()


assert snake('fooBar') == snake('FooBar') == 'foo_bar'


def unwrapped_markdown(s):
    s = highlighted_markdown(s)
    s = strip_required_prefix(s, "<p>")
    s = strip_required_suffix(s, "</p>")
    return s


def format_exception_string():
    return ''.join(traceback.format_exception_only(*sys.exc_info()[:2]))


def is_valid_syntax(text):
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False


def highlighted_markdown_and_codes(text):
    from markdown import markdown
    from .markdown_extensions import HighlightPythonExtension

    extension = HighlightPythonExtension()
    extension.codes = []
    return markdown(text, extensions=[extension, 'markdown.extensions.tables']), extension.codes


def highlighted_markdown(text):
    return highlighted_markdown_and_codes(text)[0]


def markdown_codes(text):
    return highlighted_markdown_and_codes(text)[1]


def shuffled(it):
    result = list(it)
    shuffle(result)
    return result


def shuffled_well(seq):
    original = range(len(seq))
    permutations = {
        tuple(shuffled(original))
        for _ in range(10)
    }

    def inversions(perm):
        return sum(
            perm[i] > perm[j]
            for i, j in combinations(original, 2)
        )

    permutation = sorted(permutations, key=inversions)[-2]
    return [seq[i] for i in permutation]


class MyASTTokens(ASTTokens):
    def get_text_pos(self, lineno, col_offset):
        col_offset = self._line_numbers.from_utf8_col(lineno, col_offset)
        return self._line_numbers.line_to_offset(lineno, col_offset)

    def get_text_range(self, node):
        return (
            self.get_text_pos(node.lineno, node.col_offset),
            self.get_text_pos(node.end_lineno, node.end_col_offset),
        )

    def get_text(self, node):
        result = super().get_text(node)
        assert result == ast.get_source_segment(self._text, node)
        return result


def check_and_remove_prefix(string, prefix):
    if startswith := string.startswith(prefix):
        string = strip_required_prefix(string, prefix)
    return string, startswith


def get_exception_event():
    import sentry_sdk

    os.environ["SENTRY_RELEASE"] = "stubbed"  # TODO get git commit?

    event = {}

    def transport(e):
        nonlocal event
        event = e

    client = sentry_sdk.Client(transport=transport)
    hub = sentry_sdk.Hub(client)
    hub.capture_exception()

    assert event
    return event


def truncate(seq, max_length, middle):
    if len(seq) > max_length:
        left = (max_length - len(middle)) // 2
        right = max_length - len(middle) - left
        seq = seq[:left] + middle + seq[-right:]
    return seq


def truncate_string(string, max_length):
    return truncate(string, max_length, "...")


def safe_traceback(e: Exception):
    import stack_data

    try:
        return "".join(
            stack_data.Formatter(show_variables=True, chain=True).format_exception(e)
        )
    except Exception:
        pass
    try:
        return "".join(
            stack_data.Formatter(show_variables=False, chain=True).format_exception(e)
        )
    except Exception:
        pass
    try:
        return "".join(
            stack_data.Formatter(show_variables=True, chain=False).format_exception(e)
        )
    except Exception:
        pass
    try:
        return "".join(
            stack_data.Formatter(show_variables=False, chain=False).format_exception(e)
        )
    except Exception:
        return "".join(traceback.format_exception(type(e), e, e.__traceback__))


def internal_error_result(e: Exception):
    exception_string = "".join(traceback.format_exception_only(type(e), e))

    return dict(
        error=dict(
            details=safe_traceback(e),
            title=f"Internal error: {truncate_string(exception_string, 100)}",
            sentry_event=get_exception_event(),
        ),
    )


def catch_internal_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if TESTING:
                raise
            return internal_error_result(e)
    return wrapper
