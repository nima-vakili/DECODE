import math
import time
import torch
import hashlib
import pathlib


def hash_model(modelfile):
    """
    Calculate hash and show it to the user.
    (https://www.pythoncentral.io/hashing-files-with-python/)
    """
    blocksize = 65536
    hasher = hashlib.sha1()
    with open(modelfile, 'rb') as afile:
        buf = afile.read(blocksize)
        while len(buf) > 0:
            hasher.update(buf)
            buf = afile.read(blocksize)
    return hasher.hexdigest()


class LoadSaveModel:
    def __init__(self, model_instance, output_file: (str, pathlib.Path), input_file=None, name_time_interval=(60*60), better_th=1e-6,
                 max_files=3):
        """

        :param model_instance:
        :param output_file:
        :param input_file:
        :param name_time_interval:
        :param better_th: relative threshold on a metric to determine whether a model is better or not.
        """

        self.warmstart_file = pathlib.Path(input_file) if input_file is not None else None
        self.output_file = pathlib.Path(output_file) if output_file is not None else None
        self.output_file_suffix = -1  # because will be increased to one in the first round
        self.model = model_instance
        self.name_time_interval = name_time_interval

        self._last_saved = 0  # timestamp when it was saved last
        self._new_name_time = 0   # timestamp when the name changed last
        self._best_metric_val = math.inf
        self.better_th = better_th
        self.max_files = max_files if ((max_files is not None) or (max_files != -1)) else float('inf')

    def _create_target_folder(self):
        """
        Creates the target folder for the network output .pt file, if it does not exists already
        :return:
        """
        p = pathlib.Path(self.output_file)
        try:
            pathlib.Path(p.parents[0]).mkdir(parents=False, exist_ok=True)
        except FileNotFoundError:
            raise FileNotFoundError("I will only create the last folder for model saving. But the path you specified "
                                    "lacks more folders or is completely wrong.")

    def load_init(self, cuda=torch.cuda.is_available()):
        model = self.model
        print('Model instantiated.')
        if self.warmstart_file is None:
            # model.weight_init()
            print('Model initialised randomly as specified in the constructor.')
        else:
            hashv = hash_model(self.warmstart_file)
            print(f'Model SHA-1 hash: {hashv}')
            model.hash = hashv

            if cuda:
                model.load_state_dict(torch.load(self.warmstart_file))
            else:
                model.load_state_dict(torch.load(self.warmstart_file, map_location='cpu'))

            print('Loaded pretrained model: {}'.format(self.warmstart_file))

        model.eval()
        return model

    def save(self, model, metric_val=None):
        """
        Saves the model if it is better than before
        :param model:
        :param metric_val:
        :return:
        """
        # create folder if does not exists
        self._create_target_folder()

        if metric_val is not None:
            """If relative difference to previous value is less than threshold difference, do not save."""
            rel_diff = metric_val / self._best_metric_val
            if rel_diff <= 1 - self.better_th:
                self._best_metric_val = metric_val
            else:
                return

        """After a certain period, change the suffix."""
        if (time.time() > self._new_name_time + self.name_time_interval) or metric_val is None:
            self.output_file_suffix += 1
            if self.output_file_suffix > self.max_files - 1:
                self.output_file_suffix = 0

            self._new_name_time = time.time()

        """Determine file name and save."""
        fname = pathlib.Path(str(self.output_file.with_suffix('')) + '_' + str(self.output_file_suffix) + '.pt')
        torch.save(model.state_dict(), fname)
        print('Saved model to file: {}'.format(fname))

        self._last_saved = time.time()
