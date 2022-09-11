import unittest
from unittest.mock import patch
import re

import torch as t
from torch import nn
import transformers
from torchtyping import TensorType

from mlab_tfs.bert import bert_student, bert_reference
from mlab_tfs.utils.mlab_utils import itpeek

# Base test class
# TODO move somewhere better


class MLTest(unittest.TestCase):
    def assert_tensors_close(self, student_out: TensorType, reference_out: TensorType, tol=1e-5):
        """Assert that two tensors have the same size and all elements are close."""
        message = f'Mismatched shapes!\nExpected:\n{student_out.shape}\nFound:\n{reference_out.shape}'
        self.assertEqual(reference_out.shape, student_out.shape, message)

        message = f'Not all values are close!\nExpected:\n{itpeek(reference_out)}\nFound:\n{itpeek(student_out)}'
        self.assertTrue(t.allclose(reference_out, student_out, rtol=1e-4, atol=tol), message)


# Utility functions.
# TODO move somewhere better
def get_pretrained_bert():
    """Get just the pretrained reference BERT, discarding the HF BERT."""
    pretrained_bert, _ = bert_reference.my_bert_from_hf_weights()
    return pretrained_bert


def mapkey(key):
    """Map a key from Hugging Face BERT's parameters to our BERT's parameters."""
    key = re.sub(r'^embedding\.', 'embed.', key)
    key = re.sub(r'\.position_embedding\.', '.pos_embedding.', key)
    key = re.sub(r'^lm_head\.mlp\.', 'lin.', key)
    key = re.sub(r'^lm_head\.unembedding\.', 'unembed.', key)
    key = re.sub(r'^lm_head\.layer_norm\.', 'layer_norm.', key)
    key = re.sub(r'^transformer\.([0-9]+)\.layer_norm',
                 'blocks.\\1.layernorm1', key)
    key = re.sub(r'^transformer\.([0-9]+)\.attention\.pattern\.',
                 'blocks.\\1.attention.', key)
    key = re.sub(r'^transformer\.([0-9]+)\.residual\.layer_norm\.',
                 'blocks.\\1.layernorm2.', key)

    key = re.sub(r'^transformer\.', 'blocks.', key)
    key = re.sub(r'\.project_out\.', '.project_output.', key)
    key = re.sub(r'\.residual\.mlp', '.mlp.lin', key)
    return key


class TestBertLayerNorm(MLTest):
    """Test layer normalization functionality."""

    @ patch('torch.nn.functional.layer_norm')
    def test_no_cheating(self, patched_function):
        """Test that the student doesn't call the PyTorch version."""
        ln1 = bert_student.LayerNorm(2)
        input = t.randn(10, 2)
        ln1(input)
        patched_function.assert_not_called()

    def test_layer_norm_2d(self):
        """Test a 2D input tensor."""
        ln1 = bert_student.LayerNorm(10)
        ln2 = nn.LayerNorm(10)
        t.random.manual_seed(42)
        input = t.randn(20, 10)
        self.assert_tensors_close(ln1(input), ln2(input))

    def test_layer_norm_3d(self):
        """Test a 3D input tensor."""
        ln1 = bert_student.LayerNorm((10, 5))
        ln2 = nn.LayerNorm((10, 5))
        t.random.manual_seed(42)
        input = t.randn(20, 10, 5)
        self.assert_tensors_close(ln1(input), ln2(input))

    def test_layer_norm_transformer(self):
        """Test a transformer-sized input tensor."""
        ln1 = bert_student.LayerNorm(768)
        ln2 = nn.LayerNorm(768)
        t.random.manual_seed(42)
        input = t.randn(20, 32, 768)
        self.assert_tensors_close(ln1(input), ln2(input))

    def test_layer_norm_variables(self):
        """Modify weight and bias and test for the same output."""
        ln1 = bert_student.LayerNorm(10)
        ln2 = nn.LayerNorm(10)
        t.random.manual_seed(42)
        weight = nn.Parameter(t.randn(10))
        bias = nn.Parameter(t.randn(10))
        ln1.weight.set = weight
        ln2.weight.set = weight
        ln1.bias = bias
        ln2.bias = bias
        input = t.randn(20, 10)
        self.assert_tensors_close(ln1(input), ln2(input))


class TestBertEmbedding(MLTest):
    """Test embedding functionality."""

    @patch('torch.nn.Embedding.forward')
    def test_no_cheating(self, patched_function):
        """Test that the student doesn't call the PyTorch version."""
        emb1 = bert_student.Embedding(10, 5)
        random_input = t.randint(0, 10, (2, 3))
        emb1(random_input)
        patched_function.assert_not_called()

    def test_attribute_types(self):
        """Test the types of the module's attributes."""
        emb1 = bert_student.BertEmbedding(28996, 768, 512, 2, 0.1)
        self.assertIsInstance(emb1.position_embedding, bert_student.Embedding)
        self.assertIsInstance(emb1.token_embedding, bert_student.Embedding)
        self.assertIsInstance(emb1.token_type_embedding, bert_student.Embedding)
        self.assertIsInstance(emb1.layer_norm, bert_student.LayerNorm)
        self.assertIsInstance(emb1.dropout, t.nn.Dropout)

    def test_embedding(self):
        """Test bert_student.Embedding for parity with nn.Embedding."""
        random_input = t.randint(0, 10, (2, 3))
        t.manual_seed(1157)
        emb1 = bert_student.Embedding(10, 5)
        t.manual_seed(1157)
        emb2 = nn.Embedding(10, 5)
        self.assert_tensors_close(emb1(random_input), emb2(random_input))

    def test_bert_embedding(self):
        """Test bert_student.BertEmbedding for parity with bert_reference.BertEmbedding."""
        config = {
            "vocab_size": 28996,
            "hidden_size": 768,
            "max_position_embeddings": 512,
            "type_vocab_size": 2,
            "dropout": 0.1,
        }
        t.random.manual_seed(0)
        input_ids = t.randint(0, 2900, (2, 3))
        tt_ids = t.randint(0, 2, (2, 3))
        t.random.manual_seed(0)
        reference = bert_reference.BertEmbedding(config)
        reference.eval()
        t.random.manual_seed(0)
        yours = bert_student.BertEmbedding(**config)
        yours.eval()
        self.assert_tensors_close(
            yours(input_ids=input_ids, token_type_ids=tt_ids),
            reference(input_ids=input_ids, token_type_ids=tt_ids)
        )


class TestGELU(MLTest):
    """Test GELU functionality."""

    @patch('torch.nn.GELU.forward')
    def test_no_cheating(self, patched_function):
        """Test that the student doesn't call the PyTorch version."""
        emb1 = bert_student.Embedding(10, 5)
        random_input = t.randint(0, 10, (2, 3))
        emb1(random_input)
        patched_function.assert_not_called()

    def test_gelu(self):
        """Test bert_student.GELU for parity with bert_reference.gelu and torch.nn.GELU."""
        student = bert_student.GELU()
        reference1 = bert_reference.gelu
        reference2 = t.nn.GELU()
        t.random.manual_seed(0)
        input = t.randn(20, 30)
        self.assert_tensors_close(student(input), reference1(input))
        self.assert_tensors_close(student(input), reference2(input))


class TestBertMLP(MLTest):

    def test_bert_mlp(self):
        reference = bert_reference.bert_mlp
        hidden_size = 768
        intermediate_size = 4 * hidden_size

        token_activations = t.empty(2, 3, hidden_size).uniform_(-1, 1)
        mlp_1 = nn.Linear(hidden_size, intermediate_size)
        mlp_2 = nn.Linear(intermediate_size, hidden_size)
        dropout = t.nn.Dropout(0.1)
        dropout.eval()
        self.assert_tensors_close(
            bert_student.bert_mlp(token_activations=token_activations,
                                  linear_1=mlp_1, linear_2=mlp_2),
            reference(
                token_activations=token_activations,
                linear_1=mlp_1,
                linear_2=mlp_2,
                dropout=dropout,
            )
        )


class TestBertAttention(MLTest):
    """Test multi-headed self-attention functionality."""

    def test_attention_fn(self):
        reference = bert_reference.multi_head_self_attention
        hidden_size = 768
        batch_size = 2
        seq_length = 3
        num_heads = 12
        token_activations = t.empty(
            batch_size, seq_length, hidden_size).uniform_(-1, 1)
        attention_pattern = t.rand(
            batch_size, num_heads, seq_length, seq_length)
        project_value = nn.Linear(hidden_size, hidden_size)
        project_output = nn.Linear(hidden_size, hidden_size)
        dropout = t.nn.Dropout(0.1)
        dropout.eval()
        self.assert_tensors_close(
            bert_student.bert_attention(
                token_activations=token_activations,
                num_heads=num_heads,
                attention_pattern=attention_pattern,
                project_value=project_value,
                # project_out=project_output,
                project_output=project_output,
                # dropout=dropout,
            ),
            reference(
                token_activations=token_activations,
                num_heads=num_heads,
                attention_pattern=attention_pattern,
                project_value=project_value,
                project_out=project_output,
                dropout=dropout,
            )
        )

    def test_attention_pattern_fn(self):
        reference = bert_reference.raw_attention_pattern
        hidden_size = 768
        token_activations = t.empty(2, 3, hidden_size).uniform_(-1, 1)
        num_heads = 12
        project_query = nn.Linear(hidden_size, hidden_size)
        project_key = nn.Linear(hidden_size, hidden_size)
        self.assert_tensors_close(
            bert_student.raw_attention_pattern(
                token_activations=token_activations,
                num_heads=num_heads,
                project_query=project_query,
                project_key=project_key,
            ),
            reference(
                token_activations=token_activations,
                num_heads=num_heads,
                project_query=project_query,
                project_key=project_key,
            )
        )

    def test_attention_pattern_single_head(self):
        """Note: Unused in the original MLAB repo."""
        pass
        # reference = bert_reference.raw_attention_pattern
        # hidden_size = 768
        # token_activations = t.empty(2, 3, hidden_size).uniform_(-1, 1)
        # num_heads = 12
        # project_query = nn.Linear(hidden_size, hidden_size)
        # project_key = nn.Linear(hidden_size, hidden_size)
        # head_size = hidden_size // num_heads
        # project_query_ub = nn.Linear(hidden_size, head_size)
        # project_query_ub.weight = nn.Parameter(
        #     project_query.weight[:head_size])
        # project_query_ub.bias = nn.Parameter(project_query.bias[:head_size])
        # project_key_ub = nn.Linear(hidden_size, head_size)
        # project_key_ub.weight = nn.Parameter(project_key.weight[:head_size])
        # project_key_ub.bias = nn.Parameter(project_key.bias[:head_size])
        # self.assertAllClose(
        #     bert_sol.raw_attention_pattern(
        #         token_activations=token_activations[0],
        #         num_heads=num_heads,
        #         project_query=project_query_ub,
        #         project_key=project_key_ub,
        #     ),
        #     reference(
        #         token_activations=token_activations,
        #         num_heads=num_heads,
        #         project_query=project_query,
        #         project_key=project_key,
        #     )[0, 0, :, :]
        # )

    def test_bert_attention(self):
        config = {
            "vocab_size": 28996,
            "intermediate_size": 3072,
            "hidden_size": 768,
            "num_layers": 12,
            "num_heads": 12,
            "max_position_embeddings": 512,
            "dropout": 0.0,  # not testing dropout!!
            "type_vocab_size": 2,
        }
        t.random.manual_seed(0)
        reference = bert_reference.SelfAttentionLayer(config)
        reference.eval()
        t.random.manual_seed(0)
        theirs = bert_student.MultiHeadedSelfAttention(
            hidden_size=config["hidden_size"],
            num_heads=config["num_heads"],
            # dropout=config["dropout"],
        )
        theirs.eval()
        input_activations = t.rand((2, 3, 768))
        self.assert_tensors_close(
            theirs(input_activations),
            reference(input_activations)
        )

    def test_bert_attention_pattern(self):
        """Note: Unused in the original MLAB repo."""
        pass
        # config = {
        #     "vocab_size": 28996,
        #     "intermediate_size": 3072,
        #     "hidden_size": 768,
        #     "num_layers": 12,
        #     "num_heads": 12,
        #     "max_position_embeddings": 512,
        #     "dropout": 0.1,
        #     "type_vocab_size": 2,
        # }
        # t.random.manual_seed(0)
        # reference = bert_reference.AttentionPattern(config)
        # reference.eval()
        # t.random.manual_seed(0)
        # theirs = bert_sol.Atten(
        #     hidden_size=config["hidden_size"],
        #     num_heads=config["num_heads"],
        #     dropout=config["dropout"],
        # )
        # theirs.eval()
        # input_activations = t.rand((2, 3, 768))
        # self.assertAllClose(
        #     theirs(input_activations),
        #     reference(input_activations),
        # )


class TestBertBlock(MLTest):
    def test_bert_block(self):
        config = {
            "vocab_size": 28996,
            "intermediate_size": 3072,
            "hidden_size": 768,
            "num_layers": 12,
            "num_heads": 12,
            "max_position_embeddings": 512,
            "dropout": 0.1,
            "type_vocab_size": 2,
        }
        t.random.manual_seed(0)
        reference = bert_reference.BertBlock(config)
        reference.eval()
        t.random.manual_seed(0)
        theirs = bert_student.BertBlock(
            intermediate_size=config["intermediate_size"],
            hidden_size=config["hidden_size"],
            num_heads=config["num_heads"],
            dropout=config["dropout"],
        )
        theirs.eval()
        input_activations = t.rand((2, 3, 768))
        self.assert_tensors_close(
            theirs(input_activations),
            reference(input_activations)
        )


class TestBertEndToEnd(MLTest):
    """Involves loading pretrained weights."""

    def test_bert_logits(self):
        config = {
            "vocab_size": 28996,
            "intermediate_size": 3072,
            "hidden_size": 768,
            "num_layers": 12,
            "num_heads": 12,
            "max_position_embeddings": 512,
            "dropout": 0.1,
            "type_vocab_size": 2,
        }
        t.random.manual_seed(0)
        reference = bert_reference.Bert(config)
        reference.eval()
        t.random.manual_seed(0)
        theirs = bert_student.Bert(**config)
        theirs.eval()
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            "bert-base-cased")
        input_ids = tokenizer("hello there", return_tensors="pt")["input_ids"]
        self.assert_tensors_close(
            theirs(input_ids=input_ids),
            reference(input_ids=input_ids).logits
        )

    def test_bert_classification(self):
        config = {
            "vocab_size": 28996,
            "intermediate_size": 3072,
            "hidden_size": 768,
            "num_layers": 12,
            "num_heads": 12,
            "max_position_embeddings": 512,
            "dropout": 0.1,
            "type_vocab_size": 2,
            "num_classes": 2,
        }
        t.random.manual_seed(0)
        reference = bert_reference.Bert(config)
        reference.eval()
        t.random.manual_seed(0)
        theirs = bert_student.BertWithClassify(**config)
        theirs.eval()
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            "bert-base-cased")
        input_ids = tokenizer("hello there", return_tensors="pt")["input_ids"]
        logits, classifs = theirs(input_ids=input_ids)
        self.assert_tensors_close(
            logits,
            reference(input_ids=input_ids).logits,
        )

        self.assert_tensors_close(
            classifs,
            reference(input_ids=input_ids).classification,
        )

    def test_same_output_with_pretrained_weights(self):
        my_bert = bert_student.Bert(
            vocab_size=28996, hidden_size=768, max_position_embeddings=512,
            type_vocab_size=2, dropout=0.1, intermediate_size=3072,
            num_heads=12, num_layers=12
        )
        pretrained_bert = get_pretrained_bert()
        mapped_params = {mapkey(k): v for k, v in pretrained_bert.state_dict().items()
                         if not k.startswith('classification_head')}
        my_bert.load_state_dict(mapped_params)
        tol = 1e-4
        vocab_size = pretrained_bert.embedding.token_embedding.weight.shape[0]
        input_ids = t.randint(0, vocab_size, (10, 20))
        self.assert_tensors_close(
            my_bert.eval()(input_ids),
            pretrained_bert.eval()(input_ids).logits,
            tol=tol,
        )


if __name__ == '__main__':
    unittest.main()
