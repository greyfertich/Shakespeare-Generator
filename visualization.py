import collections
import copy
import os

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
import torch.nn as nn
import torch.nn.functional as F
from absl import app
from torch.utils.data import DataLoader, Dataset

PADDING_TOKEN = 0
CKPT_VOCABULARY_SIZE = 82
CKPT_EMBEDDING_DIM = 256
CKPT_HIDDEN_SIZE = 128


class VisualizeInternalGates(nn.Module):

  def __init__(self):
    super().__init__()
    vocabulary_size = CKPT_VOCABULARY_SIZE
    embedding_dim = CKPT_EMBEDDING_DIM
    hidden_size = CKPT_HIDDEN_SIZE

    self.embedding = nn.Embedding(num_embeddings=vocabulary_size,
                                  embedding_dim=embedding_dim,
                                  padding_idx=PADDING_TOKEN)
    self.rnn_model = VisualizeCoupledLSTMCell(input_size=embedding_dim,
                                      hidden_size=hidden_size)
    self.classifier = nn.Linear(hidden_size, vocabulary_size)
    return

  def forward(self, batch_reviews):
    data = self.embedding(batch_reviews)

    state = None
    batch_size, total_steps, _ = data.shape
    internals = []
    for step in range(total_steps):
      next_h, next_c, gate_signals = self.rnn_model(data[:, step, :], state)
      internals.append(gate_signals)
      state = next_h, next_c

    logits = self.classifier(state[0])

    internals = list(zip(*internals))
    outputs = {
        'update_signals': internals[0],
        'reset_signals': internals[1],
        'cell_state_candidates': internals[2],
    }
    return logits, outputs


class VisualizeGRUCell(nn.Module):

  def __init__(self, input_size, hidden_size):
    super().__init__()

    self.input_size = input_size
    self.hidden_size = hidden_size

    self.W_z = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W_r = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))

    self.reset_parameters()

  def forward(self, x, prev_state):
    if prev_state is None:
      batch = x.shape[0]
      prev_h = torch.zeros((batch, self.hidden_size), device=x.device)
    else:
      prev_h = prev_state

    concat_hx = torch.cat((prev_h, x), dim=1)
    z = torch.sigmoid(F.linear(concat_hx, self.W_z))
    r = torch.sigmoid(F.linear(concat_hx, self.W_r))
    h_tilde = torch.tanh(F.linear(torch.cat((r * prev_h, x), dim=1), self.W))
    next_h = (1 - z) * prev_h + z * h_tilde
    return next_h, (z, r, h_tilde)

  def reset_parameters(self):
    sqrt_k = (1. / self.hidden_size)**0.5
    with torch.no_grad():
      for param in self.parameters():
        param.uniform_(-sqrt_k, sqrt_k)
    return

  def extra_repr(self):
    return 'input_size={}, hidden_size={}'.format(self.input_size,
                                                  self.hidden_size)

class VisualizeLSTMCell(nn.Module):

  def __init__(self, input_size, hidden_size):
    super().__init__()

    self.input_size = input_size
    self.hidden_size = hidden_size

    self.W_f = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W_i = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W_c = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W_o = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))

    self.reset_parameters()

  def forward(self, x, prev_state):
    if prev_state is None:
      batch = x.shape[0]
      prev_h = torch.zeros((batch, self.hidden_size), device=x.device)
      prev_c = torch.zeros((batch, self.hidden_size), device=x.device)
    else:
      prev_h, prev_c = prev_state

    concat_hx = torch.cat((prev_h, x), dim=1)


    f = torch.sigmoid(F.linear(concat_hx, self.W_f))
    i = torch.sigmoid(F.linear(concat_hx, self.W_i))
    o = torch.sigmoid(F.linear(concat_hx, self.W_o))
    c_tilde = torch.tanh(F.linear(concat_hx, self.W_c))
    next_c = (f * prev_c) + (i * c_tilde)
    next_h = o * torch.tanh(next_c)

    return next_h, next_c, (f, i, o, c_tilde)

  def reset_parameters(self):
    sqrt_k = (1. / self.hidden_size)**0.5
    with torch.no_grad():
      for param in self.parameters():
        param.uniform_(-sqrt_k, sqrt_k)
    return

  def extra_repr(self):
    return 'input_size={}, hidden_size={}'.format(self.input_size,
                                                  self.hidden_size)

class VisualizePeepholedLSTMCell(nn.Module):

  def __init__(self, input_size, hidden_size):
    super().__init__()

    self.input_size = input_size
    self.hidden_size = hidden_size

    self.W_f = nn.Parameter(torch.Tensor(hidden_size, 2*hidden_size + input_size))
    self.W_i = nn.Parameter(torch.Tensor(hidden_size, 2*hidden_size + input_size))
    self.W_c = nn.Parameter(torch.Tensor(hidden_size, 2*hidden_size + input_size))
    self.W_o = nn.Parameter(torch.Tensor(hidden_size, 2*hidden_size + input_size))

    self.reset_parameters()

  def forward(self, x, prev_state):
    if prev_state is None:
      batch = x.shape[0]
      prev_h = torch.zeros((batch, self.hidden_size), device=x.device)
      prev_c = torch.zeros((batch, self.hidden_size), device=x.device)
    else:
      prev_h, prev_c = prev_state

    concat_hx = torch.cat((prev_c, prev_h, x), dim=1)


    f = torch.sigmoid(F.linear(concat_hx, self.W_f))
    i = torch.sigmoid(F.linear(concat_hx, self.W_i))
    o = torch.sigmoid(F.linear(concat_hx, self.W_o))
    c_tilde = torch.tanh(F.linear(concat_hx, self.W_c))
    next_c = (f * prev_c) + (i * c_tilde)
    next_h = o * torch.tanh(next_c)

    return next_h, next_c, (f, i, o, c_tilde)

  def reset_parameters(self):
    sqrt_k = (1. / self.hidden_size)**0.5
    with torch.no_grad():
      for param in self.parameters():
        param.uniform_(-sqrt_k, sqrt_k)
    return

  def extra_repr(self):
    return 'input_size={}, hidden_size={}'.format(self.input_size,
                                                  self.hidden_size)

class VisualizeCoupledLSTMCell(nn.Module):

  def __init__(self, input_size, hidden_size):
    super().__init__()

    self.input_size = input_size
    self.hidden_size = hidden_size

    self.W_f = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W_c = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))
    self.W_o = nn.Parameter(torch.Tensor(hidden_size, hidden_size + input_size))

    self.reset_parameters()

  def forward(self, x, prev_state):
    if prev_state is None:
      batch = x.shape[0]
      prev_h = torch.zeros((batch, self.hidden_size), device=x.device)
      prev_c = torch.zeros((batch, self.hidden_size), device=x.device)
    else:
      prev_h, prev_c = prev_state

    concat_hx = torch.cat((prev_h, x), dim=1)


    f = torch.sigmoid(F.linear(concat_hx, self.W_f))
    o = torch.sigmoid(F.linear(concat_hx, self.W_o))
    c_tilde = torch.tanh(F.linear(concat_hx, self.W_c))
    next_c = (f * prev_c) + ((1 - f) * c_tilde)
    next_h = o * torch.tanh(next_c)

    return next_h, next_c, (f, o, c_tilde)

  def reset_parameters(self):
    sqrt_k = (1. / self.hidden_size)**0.5
    with torch.no_grad():
      for param in self.parameters():
        param.uniform_(-sqrt_k, sqrt_k)
    return

  def extra_repr(self):
    return 'input_size={}, hidden_size={}'.format(self.input_size,
                                                  self.hidden_size)


class VisualizeWarAndPeaceDataset(Dataset):

  def __init__(self, vocabulary):
    self.vocabulary = vocabulary

    # Hardcode the parameters to match the provided checkpoint
    txt_path = 'data/war_and_peace_visualize.txt'

    with open(txt_path, 'rb') as fp:
      raw_text = fp.read().strip().decode(encoding='utf-8')

    self.data = raw_text.split('\n')

    self.char2index = {x: i for (i, x) in enumerate(self.vocabulary)}
    self.index2char = {i: x for (i, x) in enumerate(self.vocabulary)}

  def __len__(self):
    return len(self.data)

  def __getitem__(self, index):
    return np.array([self.char2index[x] for x in self.data[index]]), -1

  def convert_to_chars(self, sequence):
    if isinstance(sequence, torch.Tensor):
      sequence = sequence.squeeze(0).detach().numpy().tolist()
    return [self.index2char[x] for x in sequence]


def visualize_internals(sequence_id,
                        sequence,
                        gate_name,
                        states,
                        saving_dir='visualize/'):
  states = torch.cat(states, dim=0).detach().numpy().T
  hidden_size, time_stamps = states.shape
  fig, ax = plt.subplots(figsize=(time_stamps / 5, hidden_size / 5))

  if gate_name in ['update_signals', 'reset_signals']:
    vmin = 0
  elif gate_name == 'cell_state_candidates':
    vmin = -1
  else:
    raise ValueError

  sns.heatmap(states,
              cbar=False,
              square=True,
              linewidth=0.05,
              xticklabels=sequence,
              yticklabels=False,
              vmin=vmin,
              vmax=1,
              cmap='bwr',
              ax=ax)

  plt.xlabel('Sequence')
  plt.ylabel('Hidden Cells')

  ax.xaxis.set_ticks_position('top')

  plt.tight_layout()
  os.makedirs(saving_dir, exist_ok=True)
  plt.savefig(
      os.path.join(saving_dir,
                   'S%02d_' % sequence_id + gate_name.lower() + '.png'))
  return


def war_and_peace_visualizer():
  #####################################################################
  # Implement here following the given signature                      #
  state_dict = torch.load("data/war_and_peace_model_checkpoint.pt")

  model = VisualizeInternalGates()
  # model.load_state_dict(new_model)
  # model.eval()

  vocabulary = state_dict['vocabulary']
  dataset = VisualizeWarAndPeaceDataset(vocabulary)

  data_loader = DataLoader(dataset)

  for step, (sequences, labels) in enumerate(data_loader):
      print("here")
      _, outputs = model(sequences)
      for gate in ['update_signals', 'reset_signals', 'cell_state_candidates']:
          visualize_internals(step, dataset.convert_to_chars(sequences), gate, outputs[gate])
  #####################################################################

  return

def main(unused_argvs):
  #war_and_peace_visualizer()
  war_and_peace_visualizer()

if __name__ == '__main__':
  app.run(main)
