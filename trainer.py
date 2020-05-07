import os
import argparse
from itertools import chain

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from opts import add_args
from data_loader import ClassificationVCDS, MetricLearningVCDS, transform
from model import UniversalSRModel
from loss import CosFace, PSGE2E, Prototypical

# add argparser functions
parser = argparse.ArgumentParser(description='Training options')
parser = add_args(parser)
args = parser.parse_args()
kwargs = vars(args)

# device
if torch.cuda.is_available():
    device = torch.device('cuda')
else:
    device = torch.device('cpu')

# data loader
if args.criterion_type == 'classification':
    ds = ClassificationVCDS(
        args.csv_path,
        args.win_length,
        args.hop_length,
        args.num_frames
    )
    args.num_spkr = len(ds)
elif args.criterion_type == 'metriclearning':
    ds = MetricLearningVCDS(
        args.csv_path,
        args.win_length,
        args.hop_length,
        args.num_frames,
        args.spk_samples
    )
else:
    raise ValueError('args.criterion-type: no valid criterion type')
dl = DataLoader(
    ds,
    batch_size=args.batch_size,
    shuffle=True,
    num_workers=args.num_workers
)
feature_extractor = transform(**kwargs).to(device)

# model
model = UniversalSRModel(**kwargs)
model.to(device)

# continue from checkpoint
if args.model_path:
    model.load_state_dict(
        torch.load(
            args.model_path,
            map_location=device
        )
    )

# log
log = SummaryWriter(args.logdir)

# criterion
if args.criterion == 'cosface':
    criterion = CosFace(args.repr_dim, args.num_spkr, args.m, args.s)
elif args.criterion == 'psge2e':
    criterion = PSGE2E(args.repr_dim, args.num_spkr, args.init_m, args.init_s)
elif args.criterion == 'prototypical':
    criterion = Prototypical(args.repr_dim, args.num_spkr)
else:
    raise ValueError('args.criterion: no valid criterion function')
criterion = criterion.to(device)

# optimizer
optimizer = torch.optim.Adam(
    [
        {'params': model.parameters(), 'lr': args.lr},
        {'params': criterion.parameters(), 'lr': args.criterion_lr}
    ]
)

# training loop
counter = 0
for e in range(args.num_epochs):
    print('-' * 20 + f'epoch: {e+1:02d}' + '-' * 20)
    for x, target in tqdm(dl):
        x = x.to(device)
        x = feature_extractor(x)
        target = target.to(device)

        # forward pass
        y = model(x)

        if args.criterion_type == 'classification':
            scores, loss = criterion(y, target)
            # log the accuracy
            preds = scores.topk(1, dim=1)[1]
            log.add_scalar(
                'acc',
                (preds == target).sum().item() / y.size(0),
                counter
            )
        elif args.criterion_type == 'metriclearning':
            # TODO: implement metriclearning methods
            pass

        # updata weights
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # log the loss value
        log.add_scalar('loss', loss.item(), counter)
        counter += 1

    # save model
    if args.save_model:
        torch.save(
            model.state_dict(),
            f'models/model_{e+1:02d}.pt'
        )
        torch.save(
            criterion.state_dict(),
            f'models/crit_{e+1:02d}.pt'
        )
        torch.save(
            optimizer.state_dict(),
            f'models/optim_{e+1:02d}.pt'
        )
