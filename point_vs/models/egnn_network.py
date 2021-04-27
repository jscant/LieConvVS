import torch
from egnn_pytorch import EGNN
from egnn_pytorch.egnn_pytorch import fourier_encode_dist, exists
from einops import rearrange, repeat
from eqv_transformer.utils import Swish, GlobalPool
from lie_conv.masked_batchnorm import MaskBatchNormNd
from lie_conv.utils import Pass
from torch import nn, einsum

from point_vs.models.point_neural_network import PointNeuralNetwork


class EnTransformerBlock(EGNN):
    def forward(self, x):
        if len(x) == 3:
            coors, feats, mask = x
            edges = None
        else:
            coors, feats, mask, edges = x
        b, n, d, fourier_features = *feats.shape, self.fourier_features

        rel_coors = rearrange(coors, 'b i d -> b i () d') - rearrange(
            coors, 'b j d -> b () j d')
        rel_dist = (rel_coors ** 2).sum(dim=-1, keepdim=True)

        if fourier_features > 0:
            rel_dist = fourier_encode_dist(rel_dist,
                                           num_encodings=fourier_features)
            rel_dist = rearrange(rel_dist, 'b i j () d -> b i j d')

        feats_i = repeat(feats, 'b i d -> b i n d', n=n)
        feats_j = repeat(feats, 'b j d -> b n j d', n=n)
        edge_input = torch.cat((feats_i, feats_j, rel_dist), dim=-1)

        if exists(edges):
            edge_input = torch.cat((edge_input, edges), dim=-1)

        m_ij = self.edge_mlp(edge_input)

        coor_weights = self.coors_mlp(m_ij)
        coor_weights = rearrange(coor_weights, 'b i j () -> b i j')

        coors_out = einsum('b i j, b i j c -> b i c', coor_weights,
                           rel_coors) + coors

        m_i = m_ij.sum(dim=-2)

        node_mlp_input = torch.cat((feats, m_i), dim=-1)
        node_out = self.node_mlp(node_mlp_input) + feats

        return coors_out, node_out, mask


class EnResBlock(nn.Module):

    def __init__(self, chin, chout, conv, bn=False, act='swish'):
        super().__init__()
        nonlinearity = Swish if act == 'swish' else nn.ReLU
        self.conv = conv
        self.net = nn.ModuleList([
            MaskBatchNormNd(chin) if bn else nn.Sequential(),
            Pass(nonlinearity(), dim=1),
            Pass(nn.Linear(chin, chin // 4), dim=1),
            MaskBatchNormNd(chin // 4) if bn else nn.Sequential(),
            Pass(nonlinearity(), dim=1),
            self.conv,
            MaskBatchNormNd(chout // 4) if bn else nn.Sequential(),
            Pass(nonlinearity(), dim=1),
            Pass(nn.Linear(chout // 4, chout), dim=1),
        ])
        self.chin = chin

    def forward(self, inp):
        sub_coords, sub_values, mask = inp
        for layer in self.net:
            inp = layer(inp)
        new_coords, new_values, mask = inp
        new_values[..., :self.chin] += sub_values
        return new_coords, new_values, mask


class EGNNPass(nn.Module):
    def __init__(self, egnn):
        super().__init__()
        self.egnn = egnn

    def forward(self, x):
        if len(x) == 2:
            coors, feats = x
            mask = None
        else:
            coors, feats, mask = x
        feats, coors = self.egnn(feats=feats, coors=coors, mask=mask)
        return coors, feats, mask


class EGNNStack(PointNeuralNetwork):

    @staticmethod
    def xavier_init(m):
        pass

    def _get_y_true(self, y):
        return y.cuda()

    def _process_inputs(self, x):
        return [i.cuda() for i in x]

    def build_net(self, dim_input, dim_output=1, k=12, act="swish", bn=True,
                  dropout=0.0, num_layers=6, pool=True, **kwargs):
        egnn = lambda: EGNN(dim=dim_input, m_dim=k, norm_coors=True,
                            edge_dim=0, norm_feats=False, dropout=dropout)
        if act == 'swish':
            activation_class = Swish
        elif act == 'relu':
            activation_class = nn.ReLU
        else:
            raise NotImplementedError('{} not a recognised activation'.format(
                act))
        self.layers = nn.Sequential(
            *[EGNNPass(egnn()) for _ in range(num_layers)],
            GlobalPool(mean=True) if pool else nn.Sequential(),
            nn.Linear(dim_input, dim_output)
        )

    def forward(self, x):
        return self.layers(x)

    @staticmethod
    def get_min_max(network):
        for layer in network:
            if isinstance(layer, Pass):
                if isinstance(layer.module, nn.Linear):
                    print('Linear:',
                          float(torch.min(layer.module.weight)),
                          float(torch.max(layer.module.weight)))
            elif isinstance(layer, EGNN):
                for network_type, network_name in zip(
                        (layer.edge_mlp, layer.node_mlp, layer.coors_mlp),
                        ('EGNN-edge', 'EGNN-node', 'EGNN-coors')):
                    for sublayer in network_type:
                        if isinstance(sublayer, nn.Linear):
                            print(network_name,
                                  float(torch.min(sublayer.weight)),
                                  float(torch.max(sublayer.weight)))
