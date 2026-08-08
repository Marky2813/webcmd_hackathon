"""ADK tools. Docstrings here become the tool schemas the model sees."""

from shopper.tools.cart_tools import prepare_cart
from shopper.tools.profile_tools import (
    get_profile,
    remember_taste,
    save_profile,
    update_preference,
)
from shopper.tools.search_tools import search_products

ALL_TOOLS = [
    save_profile,
    get_profile,
    update_preference,
    remember_taste,
    search_products,
    prepare_cart,
]
