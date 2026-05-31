# palimind



### install
In the main directory:

`pip install -e .`

This installs the `pm` CLI for the palimind package.

### ollama models
`ollama pull nomic-embed-text`
`ollama pull llava`
`ollama pull llama3`

## how to use
`cd /your/project`

### initialise
`pm init`

### ask questions
`pm ask "how does authentication work?"`

### chat with the model
`pm chat`

### update the embeddings with new files
`pm add`          


for now it uses nomic-embed-text for embeddings and ollama3 for answering queries
