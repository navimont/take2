def a():
    def b():
      print c

    c = 3
    return b

bb = a()
bb()
