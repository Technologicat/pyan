"""Within-scope self-references (#127): the attribute-uses fallback should
suppress edges where the calling site lies inside the defined ancestor it
would otherwise emit to. A method reading an undefined attribute on its
own class is just normal scoping; a function reading module-level state in
its own module likewise. Either way, the resulting "X uses X-or-its-parent"
edge is trivially true and surfaces no useful coupling.
"""


class Holder:
    def reads_self(self):
        return Holder.runtime_only_attr  # within-class self-reference

    def writes_self(self, value):
        Holder.runtime_only_attr = value  # within-class self-write


class Sibling:
    def reads_holder(self):
        return Holder.runtime_only_attr  # cross-class — edge SHOULD fire
