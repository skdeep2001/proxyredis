
from proxycache.linkedlist import LinkedList
from proxycache.linkedlist import Node

def test_linkedlist_empty():
    l = LinkedList()
    assert l.head is None
    assert l.tail is None

def test_linkedlist_ins_1node():
    l = LinkedList()
    n1 = Node(1, 1)
    l.add_to_head(n1)

    assert l.head == n1
    assert l.tail == n1

    assert n1.prev is None
    assert n1.next is None

def test_linkedlist_ins_del_1node():
    l = LinkedList()
    n1 = Node(1, 1)
    l.add_to_head(n1)
    l.remove(n1)

    assert l.head is None
    assert l.tail is None

    assert n1.prev is None
    assert n1.next is None

def test_linkedlist_ins_2node():
    l = LinkedList()
    n1 = Node(1, 1)
    n2 = Node(2, 2)
    l.add_to_head(n2)
    l.add_to_head(n1)

    assert l.head == n1
    assert l.tail == n2

    assert n1.prev is None
    assert n1.next == n2
    assert n2.prev == n1
    assert n2.next is None

def test_linkedlist_ins_2node_del_head():
    l = LinkedList()
    n1 = Node(1, 1)
    n2 = Node(2, 2)
    l.add_to_head(n2)
    l.add_to_head(n1)
    l.remove(l.head)

    assert l.head == n2
    assert l.tail == n2

    assert n2.prev is None
    assert n2.next is None
    assert n2.prev is None
    assert n2.next is None

def test_linkedlist_ins_2node_del_tail():
    l = LinkedList()
    n1 = Node(1, 1)
    n2 = Node(2, 2)
    l.add_to_head(n2)
    l.add_to_head(n1)
    l.remove(l.tail)

    assert l.head == n1
    assert l.tail == n1

    assert n1.prev is None
    assert n1.next is None
    assert n2.prev is None
    assert n2.next is None