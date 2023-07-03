from hashlib import sha256
import json
import time

from flask import Flask, request
import requests


class Block:
    def __init__(self, index, transactions, timestamp, previous_hash, nonce=0):
        self.index = index
        self.transactions = transactions
        self.timestamp = timestamp
        self.previous_hash = previous_hash
        self.nonce = nonce

    def compute_hash(self):
        """
        Função que retorna o hash do bloco
        """
        block_string = json.dumps(self.__dict__, sort_keys=True)
        return sha256(block_string.encode()).hexdigest()


class Blockchain:
    # Seta o critério de dificuldade do algoritmo de PoW
    difficulty = 2

    def __init__(self):
        self.unconfirmed_transactions = []
        self.chain = []

    def create_genesis_block(self):
        """
        Função para gerar e inserir o bloco originário na cadeia.
        O bloco tem index 0, previous_hash 0 e um hash válido.
        """
        genesis_block = Block(0, [], 0, "0")
        genesis_block.hash = genesis_block.compute_hash()
        self.chain.append(genesis_block)

    @property
    def last_block(self):
        return self.chain[-1]

    def add_block(self, block, proof):
        """
        Função que adiciona blocos à cadeia após verificação.
        É verificado:
        * Se a PoW é válida.
        * Se o previous_hash referenciado condiz com o hash do último bloco inserido.
        """
        previous_hash = self.last_block.hash

        if previous_hash != block.previous_hash:
            return False

        if not Blockchain.is_valid_proof(block, proof):
            return False

        block.hash = proof
        self.chain.append(block)
        return True

    @staticmethod
    def proof_of_work(block):
        """
        Função que testa diferentes valores para o nonce até achar
        um hash que satisfaça o critério de dificuldade.
        """
        block.nonce = 0

        computed_hash = block.compute_hash()
        while not computed_hash.startswith('0' * Blockchain.difficulty):
            block.nonce += 1
            computed_hash = block.compute_hash()

        return computed_hash

    def add_new_transaction(self, transaction):
        self.unconfirmed_transactions.append(transaction)

    @classmethod
    def is_valid_proof(cls, block, block_hash):
        """
        Verifica se o blosk_hash é um hash válido e se satisfaz
        o critério de dificuldade.
        """
        return (block_hash.startswith('0' * Blockchain.difficulty) and
                block_hash == block.compute_hash())

    @classmethod
    def check_chain_validity(cls, chain):
        result = True
        previous_hash = "0"

        for block in chain:
            block_hash = block.hash
            # Remove os campos de hash para recalcula-los usando o método 'compute_hash'.
            delattr(block, "hash")

            if not cls.is_valid_proof(block, block_hash) or \
                    previous_hash != block.previous_hash:
                result = False
                break

            block.hash, previous_hash = block_hash, block_hash

        return result

    def mine(self):
        """
        Função que serve como interface para adição de uma transação
        pendente na blockchain, adicionando ela no bloco e descobrido
        sua Proof of Work.
        """
        if not self.unconfirmed_transactions:
            return False

        last_block = self.last_block

        new_block = Block(index=last_block.index + 1,
                          transactions=self.unconfirmed_transactions,
                          timestamp=time.time(),
                          previous_hash=last_block.hash)

        proof = self.proof_of_work(new_block)
        self.add_block(new_block, proof)

        self.unconfirmed_transactions = []

        return True


app = Flask(__name__)

# cria o node da blockchain
blockchain = Blockchain()
blockchain.create_genesis_block()

# endereço para outros membros participantes da rede
peers = set()


# endpoint de envio de nova transação
@app.route('/new_transaction', methods=['POST'])
def new_transaction():
    tx_data = request.get_json()
    required_fields = ["author", "content"]

    for field in required_fields:
        if not tx_data.get(field):
            return "Dados de transação inválidos", 404

    tx_data["timestamp"] = time.time()

    blockchain.add_new_transaction(tx_data)

    return "Sucesso", 201


# endpoint que retorna todos os blocos na cadeia
@app.route('/chain', methods=['GET'])
def get_chain():
    chain_data = []
    for block in blockchain.chain:
        chain_data.append(block.__dict__)
    return json.dumps({"length": len(chain_data),
                       "chain": chain_data,
                       "peers": list(peers)})


# endpoint para iniciar mineiração de transações ainda não confirmadas (se existir).
@app.route('/mine', methods=['GET'])
def mine_unconfirmed_transactions():
    result = blockchain.mine()
    if not result:
        return "Não há transações para mineirar"
    else:
        # Certifica que temos a cadeia mais longa antes de anunciar à rede
        chain_length = len(blockchain.chain)
        consensus()
        if chain_length == len(blockchain.chain):
            # anunciar o bloco recentemente extraído para a rede
            announce_new_block(blockchain.last_block)
        return "Bloco #{} foi mineirado.".format(blockchain.last_block.index)


# endpoint para adicionar novos pares à rede
@app.route('/register_node', methods=['POST'])
def register_new_peers():
    node_address = request.get_json()["node_address"]
    if not node_address:
        return "Dados inválidos", 400

    # Adiciona o nó para a lista de pares
    peers.add(node_address)

    # Retorna a função get_chain() para sincronizar a cadeia
    return get_chain()


@app.route('/register_with', methods=['POST'])
def register_with_existing_node():
    """
    Chama internamente o endpoint `register_node` 
    para registrar o nó atual com o nó especificado 
    no request e sincronizar o blockchain.
    """
    node_address = request.get_json()["node_address"]
    if not node_address:
        return "Dados inválidos", 400

    data = {"node_address": request.host_url}
    headers = {'Content-Type': "application/json"}

    # Request para obter informações do nó
    response = requests.post(node_address + "/register_node",
                             data=json.dumps(data), headers=headers)

    if response.status_code == 200:
        global blockchain
        global peers
        # atualiza a cadeia e os pares
        chain_dump = response.json()['chain']
        blockchain = create_chain_from_dump(chain_dump)
        peers.update(response.json()['peers'])
        return "Registro bem sucedido", 200
    else:
        # se algo der errado, repassa a resposta da API
        return response.content, response.status_code


def create_chain_from_dump(chain_dump):
    generated_blockchain = Blockchain()
    generated_blockchain.create_genesis_block()
    for idx, block_data in enumerate(chain_dump):
        if idx == 0:
            continue  # pula o bloco originário
        block = Block(block_data["index"],
                      block_data["transactions"],
                      block_data["timestamp"],
                      block_data["previous_hash"],
                      block_data["nonce"])
        proof = block_data['hash']
        added = generated_blockchain.add_block(block, proof)
        if not added:
            raise Exception("O dump da cadeia foi adulterado!!")
    return generated_blockchain


# endpoint para adicionar bloco mineirado.
@app.route('/add_block', methods=['POST'])
def verify_and_add_block():
    block_data = request.get_json()
    block = Block(block_data["index"],
                  block_data["transactions"],
                  block_data["timestamp"],
                  block_data["previous_hash"],
                  block_data["nonce"])

    proof = block_data['hash']
    added = blockchain.add_block(block, proof)

    if not added:
        return "O bloco foi descartado pelo nó", 400

    return "Bloco adicionado à cadeia", 201


# endpoint para recuperar as transações pendentes
@app.route('/pending_tx')
def get_pending_tx():
    return json.dumps(blockchain.unconfirmed_transactions)


def consensus():
    """
    Função que atualiza a cadeia presente 
    caso uma cadeia maior válida for achada.
    """
    global blockchain

    longest_chain = None
    current_len = len(blockchain.chain)

    for node in peers:
        response = requests.get('{}chain'.format(node))
        length = response.json()['length']
        chain = response.json()['chain']
        if length > current_len and blockchain.check_chain_validity(chain):
            current_len = length
            longest_chain = chain

    if longest_chain:
        blockchain = longest_chain
        return True

    return False


def announce_new_block(block):
    """
    Funçaõ que anuncia pra rede que um novo bloco foi mineirado.
    """
    for peer in peers:
        url = "{}add_block".format(peer)
        headers = {'Content-Type': "application/json"}
        requests.post(url,
                      data=json.dumps(block.__dict__, sort_keys=True),
                      headers=headers)