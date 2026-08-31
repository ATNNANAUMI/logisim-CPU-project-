import graphviz

# Create a new Digraph
c_grammar = graphviz.Digraph(format='png', engine='dot')

# Define nodes for C grammar structure
c_grammar.node('Library', 'library =', shape='box', style='filled', fillcolor='yellow')
c_grammar.node('Function', 'function =', shape='box', style='filled', fillcolor='lightblue')
c_grammar.node('Statement', 'statement =', shape='box', style='filled', fillcolor='lightblue')
c_grammar.node('Expression', 'expression =', shape='box', style='filled', fillcolor='lightblue')

# Define library structure
c_grammar.edge('Library', 'Function', label='Function declarations')
c_grammar.edge('Library', 'EOF', label='END OF FILE')

# Define function structure
c_grammar.node('Identifier', 'IDENTIFIER', color='red', shape='ellipse')
c_grammar.edge('Function', 'Identifier')
c_grammar.edge('Function', '(', label='"("')
c_grammar.edge('Function', 'Identifier', label='Parameter declarations')
c_grammar.edge('Function', ')', label='")"')
c_grammar.edge('Function', 'Statement')

# Define statement structure
c_grammar.edge('Statement', 'Statement', label='Compound statement')
c_grammar.edge('Statement', 'if', label='"if"')
c_grammar.edge('if', '(', label='"("')
c_grammar.edge('if', 'Expression')
c_grammar.edge('Expression', ')', label='")"')
c_grammar.edge('Expression', 'Statement')

c_grammar.edge('Statement', 'while', label='"while"')
c_grammar.edge('while', '(', label='"("')
c_grammar.edge('while', 'Expression')
c_grammar.edge('Expression', ')', label='")"')
c_grammar.edge('Expression', 'Statement')

c_grammar.edge('Statement', 'return', label='"return"')
c_grammar.edge('return', 'Expression', label='expression')
c_grammar.edge('Expression', ';', label='";"')

c_grammar.edge('Statement', 'var', label='"int" / "float" / "char" etc.')
c_grammar.edge('var', 'Identifier', label='IDENTIFIER')
c_grammar.edge('Identifier', '=', label='"="')
c_grammar.edge('Identifier', 'Expression')
c_grammar.edge('Expression', ';', label='";"')

# Define expression structure
c_grammar.edge('Expression', 'INTEGER_LITERAL', label='INTEGER LITERAL')
c_grammar.edge('Expression', 'STRING_LITERAL', label='STRING LITERAL')
c_grammar.edge('Expression', 'Identifier', label='IDENTIFIER')

c_grammar.edge('Expression', '(', label='"("')
c_grammar.edge('(', 'Expression')
c_grammar.edge('Expression', ')', label='")"')

c_grammar.edge('Expression', '[', label='"["')
c_grammar.edge('[', 'Expression')
c_grammar.edge('Expression', ']', label='"]"')

c_grammar.edge('Expression', '(', label='"("')
c_grammar.edge('(', 'Expression', label='Function call')
c_grammar.edge('Expression', ')', label='")"')

c_grammar.edge('Expression', 'Expression', label='Binary expressions')
c_grammar.edge('Expression', '+', label='"+"')
c_grammar.edge('Expression', '-', label='"-"')
c_grammar.edge('Expression', '*', label='"*"')
c_grammar.edge('Expression', '/', label='"/"')

# Render the graph
c_grammar_path = "/mnt/data/c_grammar"
c_grammar.render(c_grammar_path)

# Return the path of the rendered image
c_grammar_path + ".png"
