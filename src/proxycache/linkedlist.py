# Doubly linked list that supports adding a node at the head
# and removing an arbitrary node.

class Node:
    def __init__(self, key, value):
        self.prev = None
        self.next = None
        self.key = key
        self.value = value
        self.expiry = -1
    
    def __str__(self):
        return 'Node(addr={}, prev={}, next={})'.format(
            hex(id(self)), 
            hex(id(self.prev)) if self.prev else None,
            hex(id(self.next)) if self.next else None)

class LinkedList:

    def __init__(self):
        self.head = None
        self.tail = None

    def __str__(self):
        return 'List(head={}, tail={})'.format(
            hex(id(self.head)) if self.head else None,
            hex(id(self.tail)) if self.tail else None)
    
    def add_to_head(self, node):
        assert node is not None
        assert node.next is None
        assert node.prev is None

        if self.head:
            self.head.prev = node

        node.next = self.head
        self.head = node

        if self.tail is None:
            self.tail = self.head
        
    def remove(self, node):
        assert node is not None

        if self.head != node:
            node.prev.next = node.next
        else:
            self.head = node.next

        if self.tail != node:
            node.next.prev = node.prev
        else:
            self.tail = node.prev 

        node.next = None
        node.prev = None
