"""Open Inwoner search test data: products in their own categories, and search feedback.

Params: action (apply, feedback, remove), tag, products ([{name, keywords, category}]).
- apply: a category per distinct category name and the products, slugs starting with the tag;
  returns {"categories": {name: slug}}.
- feedback: the feedback whose remark starts with the tag, as {"feedback": [{positive, remark, query}]}.
- remove: deletes the tag's products, categories and feedback.
Saving and deleting update the search index (ELASTICSEARCH_DSL_AUTOSYNC).
"""


def run(params):
    from django.utils.text import slugify
    from open_inwoner.pdc.models import Category
    from open_inwoner.pdc.models import Product
    from open_inwoner.search.models import Feedback

    tag = params["tag"]
    feedback = Feedback.objects.filter(remark__startswith=tag)
    if params["action"] == "feedback":
        rows = [{"positive": f.positive, "remark": f.remark, "query": f.search_query} for f in feedback]
        return {"feedback": rows}
    if params["action"] == "remove":
        Product.objects.filter(slug__startswith=tag).delete()
        Category.objects.filter(slug__startswith=tag).delete()
        feedback.delete()
        return {"categories": {}}
    categories = {}
    for product in params["products"]:
        name = product["category"]
        if name not in categories:
            categories[name] = Category.add_root(name=name, slug=f"{tag}-{slugify(name)}", published=True)
        created = Product.objects.create(
            name=product["name"],
            slug=f"{tag}-{slugify(product['name'])}",
            published=True,
            summary=product["name"],
            content=product["name"],
            keywords=product.get("keywords", []),
        )
        created.categories.add(categories[name])
        created.save()  # indexes the product with its category
    return {"categories": {name: category.slug for name, category in categories.items()}}
