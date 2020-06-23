import os
import numpy as np
import tensorflow as tf
from tensorflow import keras
import ssgan_dataset_tf2
from ssgan_model_tf2 import Generator, Discriminator
import matplotlib.pyplot as plt


# 准备与真实数据的标签相乘的二进制标签掩码
def get_labeled_mask(labeled_rate, batch_size):
    labeled_mask = np.zeros([batch_size], dtype=np.float32)
    labeled_count = np.int(batch_size * labeled_rate)
    labeled_mask[range(labeled_count)] = 1.0
    np.random.shuffle(labeled_mask)
    return labeled_mask


# ########### 扩展标签，加入第n+1类标签，三类轴承数据 ############
def prepare_extended_label(label):
    # add extra label for fake data
    extended_label = tf.concat([tf.zeros([tf.shape(label)[0], 1]), label], axis=1)

    return extended_label


def d_loss_fn(generator, discriminator, batch_z, batch_x, labeled_mask, extended_label, is_training):
    fake_images = generator(batch_z, is_training)
    D_fake_features, D_fake_logits, D_fake_prob = discriminator(fake_images, is_training)
    D_real_features, D_real_logits, D_real_prob = discriminator(batch_x, is_training)

    temp = tf.nn.softmax_cross_entropy_with_logits(logits=D_real_logits, labels=extended_label)
    D_L_Supervised = tf.reduce_sum(tf.multiply(temp, labeled_mask)) / tf.reduce_sum(labeled_mask)
    D_L_RealUnsupervised = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
        logits=D_real_logits[:, 0], labels=tf.zeros_like(D_real_logits[:, 0], dtype=tf.float32)))

    D_L_FakeUnsupervised = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
        logits=D_fake_logits[:, 0], labels=tf.ones_like(D_fake_logits[:, 0], dtype=tf.float32)))

    D_L = D_L_Supervised + D_L_RealUnsupervised + D_L_FakeUnsupervised
    return D_L


def g_loss_fn(generator, discriminator, batch_z, batch_x, is_training):
    # G_L_1 -> Fake data wanna be real
    fake_images = generator(batch_z, is_training)
    D_fake_features, D_fake_logits, D_fake_prob = discriminator(fake_images, is_training)
    D_real_features, D_real_logits, D_real_prob = discriminator(batch_x, is_training)
    G_L_1 = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
        logits=D_fake_logits[:, 0], labels=tf.zeros_like(D_fake_logits[:, 0], dtype=tf.float32)))

    # G_L_2 -> Feature matching
    data_moments = tf.reduce_mean(D_real_features, axis=0)
    sample_moments = tf.reduce_mean(D_fake_features, axis=0)
    G_L_2 = tf.reduce_mean(tf.square(data_moments - sample_moments))

    G_L = G_L_1 + G_L_2

    return G_L


def accuracy(discriminator, batch_x, extended_label, is_training):
    D_real_features, D_real_logits, D_real_prob = discriminator(batch_x, is_training)
    prediction_value = tf.argmax(D_real_prob[:, 1:], 1)
    prediction = tf.equal(tf.argmax(D_real_prob[:, 1:], 1),
                          tf.argmax(extended_label[:, 1:], 1))
    acc = tf.reduce_mean(tf.cast(prediction, tf.float32))
    return acc, prediction_value


# d_losses, g_losses = [], []


def Draw(hist, show=False, save=False):
    plt.figure()
    plt.plot(hist['G_losses'], 'b', label='generator')
    plt.plot(hist['D_losses'], 'r', label='discriminator')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.legend()
    if save:
        if not os.path.exists('Loss'):
            os.mkdir('Loss')
        plt.savefig("Loss/loss.png")

    if show:
        plt.show()
    else:
        plt.close()


def main():
    batch_size = 64
    learning_rate = 0.0002
    z_dim = 100
    is_training = True
    epochs = 100
    labeled_rate = 0.2

    train_hist = {'D_losses': [], 'G_losses': []}

    generator = Generator()
    generator.build(input_shape=(1, z_dim))
    discriminator = Discriminator()
    discriminator.build(input_shape=(None, 32, 32, 1))

    g_optimizer = keras.optimizers.Adam(learning_rate=learning_rate, beta_1=0.5)
    d_optimizer = keras.optimizers.Adam(learning_rate=learning_rate, beta_1=0.5)

    no_of_batches = int(ssgan_dataset_tf2.train_X.shape[0] / batch_size) + 1
    for epoch in range(epochs):
        train_accuracies, train_D_losses, train_G_losses = [], [], []
        for i in range(no_of_batches - 1):
            # 准备训练数据
            batch_x = ssgan_dataset_tf2.train_X[i * batch_size:batch_size + i * batch_size, ]
            batch_label = ssgan_dataset_tf2.train_Y[i * batch_size:batch_size + i * batch_size, ]
            batch_reshaped = batch_x.reshape([-1, 32, 32, 1])
            batch_z = np.random.normal(0, 1, (batch_size, 1, 1, z_dim))
            mask = get_labeled_mask(labeled_rate, batch_size)
            extended_label = prepare_extended_label(batch_label)

            # 准备验证数据
            valid_data = ssgan_dataset_tf2.valid_X
            valid_label = ssgan_dataset_tf2.valid_Y
            valid_data_reshaped = valid_data.reshape([-1, 32, 32, 1])
            valid_extended_label = prepare_extended_label(valid_label)

            # 判别器前向计算
            with tf.GradientTape() as tape:
                d_loss = d_loss_fn(generator, discriminator, batch_z, batch_reshaped, mask, extended_label, is_training)
                grads = tape.gradient(d_loss, discriminator.trainable_variables)
                d_optimizer.apply_gradients(zip(grads, discriminator.trainable_variables))

            with tf.GradientTape() as tape:
                g_loss = g_loss_fn(generator, discriminator, batch_z, batch_reshaped, is_training)
                grads = tape.gradient(g_loss, generator.trainable_variables)
                g_optimizer.apply_gradients(zip(grads, generator.trainable_variables))

            train_accuracy, _ = accuracy(discriminator, valid_data_reshaped, valid_extended_label, None)
            train_accuracies.append(train_accuracy)
            # print(train_accuracies)
            print('Epoch [{}]/[{}]'.format(epoch, epochs), 'Batch evaluated [{}]/[{}]'.format(str(i + 1),
                                                                                              no_of_batches - 1))

            train_D_losses.append(d_loss)
            train_G_losses.append(g_loss)
        tr_GL = np.mean(train_G_losses)
        tr_DL = np.mean(train_D_losses)
        tr_acc = np.mean(train_accuracies)
        train_hist['D_losses'].append(np.mean(train_D_losses))
        train_hist['G_losses'].append(np.mean(train_G_losses))

        print('After epoch: ' + str(epoch + 1) + ' Generator loss: '
              + str(tr_GL) + ' Discriminator loss: ' + str(tr_DL) + ' Accuracy: ' + str(tr_acc))
    return train_hist


if __name__ == '__main__':
    train_loss = main()
    Draw(train_loss, show=True, save=True)
