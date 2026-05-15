# palimind

## usage


### install the palimind command
in the main directory do 

`pip install -e . `     

### ollama models
`ollama pull nomic-embed-text`
`ollama pull llama3`

## how to use
`cd /your/project`

### initialise
`palimind init` 

### ask questions
`palimind ask "how does authentication work?"`

### update the embeddings with new files
`palimind add`          


for now it uses nomic-embed-text for embeddings and ollama3 for answering queries
